#!/usr/bin/env bash
# Launches the Broadband Consumer Label Compliance API in the foreground.
# Dependencies are installed only when they are missing, so a re-launch of an
# already provisioned environment costs nothing.
set -e

cd "$(dirname "$0")"

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check \
    -r requirements.txt >/dev/null 2>&1 \
    || python3 -m pip install --quiet --break-system-packages \
       --disable-pip-version-check -r requirements.txt >/dev/null 2>&1
fi

export PORT="${PORT:-10000}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

exec python3 app.py
