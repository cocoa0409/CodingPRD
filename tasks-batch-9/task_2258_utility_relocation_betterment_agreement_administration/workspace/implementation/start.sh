#!/usr/bin/env bash
# Launch the API.  A fresh process every time: the in-memory store starts empty
# and the logical clock resets to 2026-08-01T00:00:00Z.
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-10000}"
export PORT

PYTHON="${PYTHON:-python3}"

if ! "$PYTHON" -c "import flask" >/dev/null 2>&1; then
  "$PYTHON" -m pip install --quiet --disable-pip-version-check flask >/dev/null 2>&1 || true
fi

exec "$PYTHON" app.py
