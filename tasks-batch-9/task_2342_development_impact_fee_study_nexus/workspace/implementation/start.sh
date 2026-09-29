#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-10000}"
export PORT

PYTHON="${PYTHON:-python3}"

if ! "$PYTHON" -c "import flask" >/dev/null 2>&1; then
  "$PYTHON" -m pip install --quiet --disable-pip-version-check -r requirements.txt >/dev/null 2>&1 \
    || "$PYTHON" -m pip install --quiet --break-system-packages -r requirements.txt >/dev/null 2>&1
fi

exec "$PYTHON" app.py
