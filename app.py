from flask import Flask, request, render_template, redirect, url_for, send_file, jsonify
import pandas as pd
import numpy as np
import os
import cv2
from PIL import Image, ImageDraw, ImageFont
import requests
import shutil
import vimeo

client = vimeo.VimeoClient(
  token='c0e83a1c6831112c116a4ec3cea1d7aa',
  key='64e67a1447b7cfb7e129fa62436751193ea984eb',
  secret='nlKJIWOn0Mat7dcTfsQnxyanI3lE/syTcJ7CNn424iB0c3Rjc7HlrR7KwjkQpGusFDW8qyXETtHqHEdmtierpL38gxmgCBaAtnWci0ZOUFeMqDjrMMnd3k6LeMSnUEA/'
)


app = Flask(__name__)

# Set a temporary folder for uploaded files
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'output_videos'
FONT_FOLDER = 'fonts'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER
app.config['FONT_FOLDER'] = FONT_FOLDER

# Ensure the folders exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)
os.makedirs(FONT_FOLDER, exist_ok=True)


@app.route('/')
def upload_form():
    video_path = os.path.join(app.config['UPLOAD_FOLDER'], 'video.mp4')
    excel_path = os.path.join(app.config['UPLOAD_FOLDER'], 'names.xlsx')

    video_exists = os.path.exists(video_path)
    excel_exists = os.path.exists(excel_path)

    return render_template('upload.html', video_exists=video_exists, excel_exists=excel_exists)


@app.route('/upload_files', methods=['POST'])
def upload_files():
    video_file = request.files.get('video')
    excel_file = request.files.get('excel')

    if video_file:
        allowed_video_extensions = {'mp4'}
        if video_file.filename.split('.')[-1].lower() not in allowed_video_extensions:
            return "Invalid video file format. Please upload an MP4 video."

        video_path = os.path.join(app.config['UPLOAD_FOLDER'], 'video.mp4')
        video_file.save(video_path)

        # Extract and save the initial frame
        frame = get_video_frame(video_path)
        initial_frame_path = os.path.join(app.static_folder, 'initial_frame.jpg')
        initial_image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        initial_image.save(initial_frame_path)

    if excel_file:
        allowed_excel_extensions = {'xlsx'}
        if excel_file.filename.split('.')[-1].lower() not in allowed_excel_extensions:
            return "Invalid Excel file format. Please upload an XLSX file."

        excel_path = os.path.join(app.config['UPLOAD_FOLDER'], 'names.xlsx')
        excel_file.save(excel_path)

    # Retrieve available fonts without the .ttf extension
    fonts = [os.path.splitext(f)[0] for f in os.listdir(app.config['FONT_FOLDER']) if f.endswith('.ttf')]

    return render_template('text_params.html', fonts=fonts)



@app.route('/upload_custom_font', methods=['POST'])
def upload_custom_font():
    custom_font = request.files.get('customFont')
    if custom_font and custom_font.filename.endswith('.ttf'):
        custom_font.save(os.path.join(app.config['FONT_FOLDER'], custom_font.filename))
        return redirect(url_for('text_params_form'))
    return jsonify({'error': 'Invalid font file or format.'}), 400


@app.route('/text_params_form')
def text_params_form():
    return render_template('text_params.html')

@app.route('/preview', methods=['POST'])
def preview():
    text = request.form['stext']
    font_size = int(request.form['font_size'])
    color = request.form['color']
    position = (request.form['position_x'], request.form['position_y'])
    font_name = request.form['font']
    font_path = os.path.join(app.config['FONT_FOLDER'], font_name + '.ttf')

    video_path = os.path.join(app.config['UPLOAD_FOLDER'], 'video.mp4')
    frame = get_video_frame(video_path)

    preview_image = overlay_text_on_image(frame, text, font_path, font_size, color, position)
    preview_image_path = os.path.join(app.static_folder, 'preview.jpg')
    preview_image.save(preview_image_path)

    return jsonify({"preview_image_url": "/static/preview.jpg"})


@app.route('/process_videos', methods=['POST'])
def process_videos():
    font_size = int(request.form['font_size'])
    color = request.form['color']
    duration = request.form['duration']
    position = (request.form['position_x'], request.form['position_y'])
    font_path = os.path.join(app.config['FONT_FOLDER'], request.form['font'] + '.ttf')
    
    excel_path = os.path.join(app.config['UPLOAD_FOLDER'], 'names.xlsx')
    if not os.path.exists(excel_path):
        return "No Excel file found. Please upload the Excel file."

    video_path = os.path.join(app.config['UPLOAD_FOLDER'], 'video.mp4')
    if not os.path.exists(video_path):
        return "No video file found. Please upload the video file."

    df = pd.read_excel(excel_path)
    names = df['Names'].tolist()

    output_dir = app.config['OUTPUT_FOLDER']
    links = []

    for name in names:
        output_video_path = os.path.join(output_dir, f"{name}.mp4")
        overlay_text_on_video(video_path, name, output_video_path, font_path, font_size, duration, color, position)

        video_uri = client.upload(output_video_path)
        video_uri = f"https://vimeo.com/manage{video_uri}"
        if video_uri:
            links.append(video_uri)
        else:
            links.append("Upload failed")
    df['Video Link'] = links
    updated_excel_filename = os.path.join(app.config['UPLOAD_FOLDER'], 'updated_names.xlsx')
    df.to_excel(updated_excel_filename, index=False)

    # Send the Excel file and then clean up
    response = send_file(updated_excel_filename, as_attachment=True)
    
    # Clear the output_videos folder
    shutil.rmtree(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    
    return response


def overlay_text_on_video(input_video_path, text, output_video_path, font_path='cambria.ttf', font_size=50, duration=10, color='white', position=('center', 'center')):
    cap = cv2.VideoCapture(input_video_path)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    out = cv2.VideoWriter(output_video_path, fourcc, fps, (width, height))
    duration = int(duration)
    text_duration_frames = int(fps * duration)

    try:
        font = ImageFont.truetype(font_path, font_size)
    except IOError:
        print(f"Could not load font at {font_path}")
        return

    frame_count = 0

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        if frame_count < text_duration_frames:
            frame = overlay_text_on_frame(frame, text, font, color, position)

        out.write(frame)
        frame_count += 1

    cap.release()
    out.release()
    cv2.destroyAllWindows()

def overlay_text_on_frame(frame, text, font, color, position):
    # Convert the OpenCV frame to a PIL image
    pil_image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

    # Create a drawing context
    draw = ImageDraw.Draw(pil_image)

    color = color.strip()

    # Calculate the size and position of the text
    text_bbox = draw.textbbox((0, 0), text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]

    if position[0] == 'center':
        text_x = (pil_image.width - text_width) // 2
    else:
        text_x = int(position[0])
    if position[1] == 'center':
        text_y = (pil_image.height - text_height) // 2
    else:
        text_y = int(position[1])

    # Draw the text on the image
    draw.text((text_x, text_y), text, font=font, fill=color)

    # Convert the PIL image back to an OpenCV image
    return cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)


def get_video_frame(video_path):
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Error opening video file: {video_path}")
        ret, frame = cap.read()
        cap.release()
        return frame
    except Exception as e:
        print(f"Error: {e}")
        return None


def overlay_text_on_image(frame, text, font_path, font_size, color, position):
    pil_image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_image)

    try:
        font = ImageFont.truetype(font_path, font_size)
    except IOError:
        print(f"Could not load font at {font_path}")
        return pil_image
    
    text_bbox = draw.textbbox((0, 0), text, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]

    if position[0] == 'center':
        text_x = (pil_image.width - text_width) // 2
    else:
        text_x = int(position[0])
    if position[1] == 'center':
        text_y = (pil_image.height - text_height) // 2
    else:
        text_y = int(position[1])

    draw.text((text_x, text_y), text, font=font, fill=color)
    return pil_image


@app.route('/loading')
def loading_page():
    return render_template('loading.html')

if __name__ == "__main__":
    app.run(debug=True)
