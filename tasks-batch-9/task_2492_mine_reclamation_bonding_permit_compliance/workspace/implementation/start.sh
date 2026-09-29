#!/usr/bin/env bash
# Launcher contract (INSTRUCTION.md): run from this directory, listen on $PORT
# (default 10000) on 0.0.0.0, stay in the foreground.
set -euo pipefail

cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
export PORT="${PORT:-10000}"

# Install only when Flask is genuinely absent, so a warm host boots instantly.
if ! "$PYTHON" -c "import flask" >/dev/null 2>&1; then
  "$PYTHON" -m pip install -q --disable-pip-version-check -r requirements.txt >/dev/null 2>&1 || true
fi

exec "$PYTHON" app.py
