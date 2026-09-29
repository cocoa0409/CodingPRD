#!/bin/bash
# Boots the Youth Orchestra Audition and Seating Service on $PORT (default 10000).
set -e
cd "$(dirname "$0")"

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt >/dev/null 2>&1 \
    || python3 -m pip install -q --break-system-packages -r requirements.txt \
    || true
fi

export PORT="${PORT:-10000}"
export PYTHONDONTWRITEBYTECODE=1
exec python3 app.py
