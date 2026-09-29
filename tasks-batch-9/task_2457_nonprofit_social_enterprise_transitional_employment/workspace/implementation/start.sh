#!/usr/bin/env bash
# Launch the API in the foreground on $PORT (default 10000), bound to 0.0.0.0.
set -e

cd "$(dirname "$0")"

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check -r requirements.txt
fi

export PORT="${PORT:-10000}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

exec python3 app.py
