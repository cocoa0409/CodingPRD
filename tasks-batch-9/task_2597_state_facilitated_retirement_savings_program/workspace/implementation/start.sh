#!/usr/bin/env bash
# Launcher: boots a fresh, empty API process in the foreground on every call.
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-10000}"
export PORT

PYTHON="${PYTHON:-python3}"

# Install Flask only when it is genuinely missing; the harness relaunches this
# script before every test and a network round trip each time would be fatal.
if ! "$PYTHON" -c "import flask" >/dev/null 2>&1; then
  "$PYTHON" -m pip install --quiet --disable-pip-version-check flask >/dev/null 2>&1 || \
    "$PYTHON" -m pip install --quiet --break-system-packages --disable-pip-version-check flask >/dev/null 2>&1 || true
fi

exec "$PYTHON" app.py
