#!/usr/bin/env bash
# Boot the Digital Accessibility Conformance API on a fresh, empty in-memory store.
set -euo pipefail

cd "$(dirname "$0")"

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

export PORT="${PORT:-10000}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

exec python3 app.py
