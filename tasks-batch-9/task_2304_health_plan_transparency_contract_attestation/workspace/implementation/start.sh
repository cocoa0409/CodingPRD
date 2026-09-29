#!/bin/bash
# Launch the compliance API in the foreground on 0.0.0.0:${PORT:-10000}.
set -e

cd "$(dirname "$0")"

export PORT="${PORT:-10000}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

# app.py installs Flask itself if the interpreter cannot import it, so the
# happy path costs exactly one interpreter launch and no extra subprocess.
exec python3 app.py
