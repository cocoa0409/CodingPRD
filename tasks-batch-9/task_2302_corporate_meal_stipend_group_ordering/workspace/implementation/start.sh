#!/usr/bin/env bash
# Launch the API in the foreground on $PORT (default 10000), binding 0.0.0.0.
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
export PORT="${PORT:-10000}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

if ! "$PYTHON" -c "import flask" >/dev/null 2>&1; then
  "$PYTHON" -m pip install -q -r requirements.txt >/dev/null 2>&1 || true
fi

exec "$PYTHON" app.py
