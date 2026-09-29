#!/usr/bin/env bash
# Launch the commuter benefit program administration API.
# The server is stateless across boots: every dict in store.py starts empty.
set -euo pipefail

cd "$(dirname "$0")"

export PORT="${PORT:-10000}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check -r requirements.txt \
    >/dev/null 2>&1 || true
fi

exec python3 app.py
