#!/bin/bash
set -e
cd "$(dirname "$0")"

if ! python3 -c "import flask" 2>/dev/null; then
  pip install -q -r requirements.txt
fi

export PORT="${PORT:-10000}"
exec python3 -m app.main
