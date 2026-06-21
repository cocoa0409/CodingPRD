#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Pick the best available Python: prefer `python` (typically a venv), fall back to python3.
if command -v python >/dev/null 2>&1; then
  PY=python
elif command -v python3 >/dev/null 2>&1; then
  PY=python3
else
  echo "No python/python3 interpreter found in PATH" >&2
  exit 1
fi

"$PY" -m pip install -q --disable-pip-version-check -r requirements.txt
exec "$PY" app.py
