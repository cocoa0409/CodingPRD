#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Pick a working Python interpreter — prefer `python`, fall back to `python3`.
if command -v python >/dev/null 2>&1; then
  PY=python
elif command -v python3 >/dev/null 2>&1; then
  PY=python3
else
  echo "No python interpreter found on PATH" >&2
  exit 1
fi

# Install dependencies via `python -m pip` so we don't depend on a `pip` shim.
"$PY" -m pip install -q -r requirements.txt

exec "$PY" app.py
