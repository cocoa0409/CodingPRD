#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Only install dependencies when they are missing. Re-running pip on every boot
# (per-test-server isolation restarts before each test, 8 rounds concurrently)
# makes startup slow and unreliable under load, causing "could not be restarted".
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py
