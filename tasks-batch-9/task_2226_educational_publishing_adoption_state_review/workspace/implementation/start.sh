#!/usr/bin/env bash
# Launch the Adoption Review Press API. Boots a fresh, empty in-memory store on
# every invocation; nothing is read from or written to disk.
set -euo pipefail

cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! "$PYTHON_BIN" -c "import flask" >/dev/null 2>&1; then
  "$PYTHON_BIN" -m pip install -q -r requirements.txt >/dev/null 2>&1 || true
fi

export PORT="${PORT:-10000}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

exec "$PYTHON_BIN" app.py
