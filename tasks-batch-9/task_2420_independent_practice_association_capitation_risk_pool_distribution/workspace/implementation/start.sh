#!/usr/bin/env bash
# Boot the API in the foreground on $PORT (default 10000), bound to 0.0.0.0.
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-10000}"
export PORT

PYTHON="${PYTHON:-python3}"

if ! "$PYTHON" -c "import flask" >/dev/null 2>&1; then
  "$PYTHON" -m pip install -q -r requirements.txt >/dev/null 2>&1 || true
fi

exec "$PYTHON" app.py
