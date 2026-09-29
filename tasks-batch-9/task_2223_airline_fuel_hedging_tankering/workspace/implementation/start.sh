#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt >/dev/null 2>&1 || true
fi

export PORT="${PORT:-8000}"
exec python3 app.py
