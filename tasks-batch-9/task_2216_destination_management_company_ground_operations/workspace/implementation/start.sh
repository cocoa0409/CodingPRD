#!/usr/bin/env bash
# Launcher for the DMC Ground Operations API.
# Binds 0.0.0.0 on $PORT (default 8080) and runs in the foreground.
set -e

cd "$(dirname "$0")"

export PORT="${PORT:-8080}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check flask >/dev/null 2>&1 || true
fi

exec python3 app.py
