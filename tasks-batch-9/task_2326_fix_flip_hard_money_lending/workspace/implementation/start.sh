#!/usr/bin/env bash
# Launch the Fix-and-Flip Hard Money Lending API in the foreground on $PORT.
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-8080}"
export PORT

PY="${PYTHON:-python3}"

if ! "$PY" -c "import flask" >/dev/null 2>&1; then
  "$PY" -m pip install -q -r requirements.txt >/dev/null 2>&1 || true
fi

exec "$PY" app.py
