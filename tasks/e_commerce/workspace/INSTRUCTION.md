# Implementation Instructions

You are building a REST API server based on the requirements in `PRD.md`.

## What You Must Produce

Place all files in the `./implementation/` directory:

1. **A `Dockerfile`** at `./implementation/Dockerfile`
2. **Implementation source code** in `./implementation/` — any language and framework

## Dockerfile Requirements

Your Dockerfile must:

- Build your application from source
- Start the server via `CMD` (not `ENTRYPOINT` with shell form)
- The server **must listen on the port specified by the `PORT` environment variable** (default: 10000)
- The server **must bind to `0.0.0.0`** (not `127.0.0.1`)
- The server must respond to HTTP requests within 60 seconds of container start

Example minimal Dockerfile (Python/Flask):

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "app.py"]
```

Example minimal Dockerfile (Node.js/Express):

```dockerfile
FROM node:18-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
CMD ["node", "server.js"]
```

All API requirements are defined in `PRD.md`. Read it carefully and implement accordingly.
