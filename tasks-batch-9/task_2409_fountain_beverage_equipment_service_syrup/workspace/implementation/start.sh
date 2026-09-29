#!/bin/bash
set -e

cd "$(dirname "$0")"

# Install Flask only when it is not already importable, so a per-test server
# relaunch costs no network round-trip.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q --disable-pip-version-check -r requirements.txt
fi

export PORT="${PORT:-10000}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

exec python3 app.py
