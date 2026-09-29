#!/bin/bash
# Launch the Food Broker Authorization & Slotting API.
#
# The dependency install is guarded so a re-launch on an already-provisioned
# machine costs nothing: the harness restarts this script before every test.
set -e

cd "$(dirname "$0")"

export PORT="${PORT:-10000}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q --disable-pip-version-check -r requirements.txt \
    || python3 -m pip install -q --disable-pip-version-check --break-system-packages -r requirements.txt
fi

exec python3 app.py
