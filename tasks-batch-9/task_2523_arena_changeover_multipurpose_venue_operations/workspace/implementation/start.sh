#!/usr/bin/env bash
# Launcher for the Arena Changeover Ops API.
#
# The server keeps all state in process memory, so every invocation of this
# script starts from a completely empty store — nothing is read from or written
# to disk, and no entity data is ever seeded.
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-10000}"
export PORT

PY="${PYTHON:-python3}"

# Flask is normally already present; install it only when it is genuinely missing.
if ! "$PY" -c "import flask" >/dev/null 2>&1; then
  "$PY" -m pip install --quiet --disable-pip-version-check flask >/dev/null 2>&1 || true
fi

exec "$PY" app.py
