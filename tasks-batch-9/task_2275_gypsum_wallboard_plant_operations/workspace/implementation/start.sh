#!/usr/bin/env bash
# Launcher for the Gypsum Wallboard Plant Operations API.
# Reads $PORT (default 10000), binds 0.0.0.0 and runs in the foreground.
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-10000}"
export PORT

PYTHON="${PYTHON:-python3}"

# Install Flask only when it is missing, so re-launches are fast.
if ! "$PYTHON" -c "import flask" >/dev/null 2>&1; then
  "$PYTHON" -m pip install --quiet --disable-pip-version-check -r requirements.txt \
    || "$PYTHON" -m pip install --quiet --disable-pip-version-check --break-system-packages -r requirements.txt
fi

exec "$PYTHON" app.py
