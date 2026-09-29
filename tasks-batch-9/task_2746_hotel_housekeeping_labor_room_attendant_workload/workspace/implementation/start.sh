#!/usr/bin/env bash
# Launch the housekeeping labour API.  A fresh process on every invocation: the
# in-memory store is rebuilt empty and the logical clock resets to 2026-08-01T00:00:00Z.
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-10000}"
export PORT

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install --quiet --disable-pip-version-check -r requirements.txt >/dev/null 2>&1 || true
fi

exec python3 app.py
