#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-10000}"
export PORT

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt >/dev/null 2>&1 \
    || python3 -m pip install -q --break-system-packages -r requirements.txt >/dev/null 2>&1 \
    || true
fi

exec python3 app.py
