FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY . /app/

ENV PORT=10000
EXPOSE 10000

CMD ["python", "app.py"]
