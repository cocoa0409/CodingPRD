#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

PORT="${PORT:-10000}"
export PORT

if ! python3 -c "import flask" >/dev/null 2>&1; then
  pip install -q flask 2>/dev/null \
    || pip3 install -q flask 2>/dev/null \
    || python3 -m pip install -q flask
fi

exec python3 app.py
