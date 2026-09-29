#!/usr/bin/env bash
# Launch the Open Data Portal API.  Boots a fresh, empty in-memory store on
# every invocation; the evaluator runs only `bash start.sh`.
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-10000}"
export PORT

PY="${PYTHON:-python3}"

if ! "$PY" -c "import flask" >/dev/null 2>&1; then
  "$PY" -m pip install --quiet --disable-pip-version-check flask >/dev/null 2>&1 || \
    "$PY" -m pip install --quiet --break-system-packages --disable-pip-version-check flask >/dev/null 2>&1 || true
fi

exec "$PY" app.py
