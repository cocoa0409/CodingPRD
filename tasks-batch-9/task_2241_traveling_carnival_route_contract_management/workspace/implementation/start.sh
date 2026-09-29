#!/usr/bin/env bash
# Launch the Traveling Carnival Route & Contract Management API in the
# foreground.  A fresh process starts with a completely empty in-memory store.
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-10000}"
export PORT

PYTHON="${PYTHON:-python3}"

if ! "$PYTHON" -c "import flask" >/dev/null 2>&1; then
  "$PYTHON" -m pip install -q -r requirements.txt >/dev/null 2>&1 || true
fi

exec "$PYTHON" app.py
