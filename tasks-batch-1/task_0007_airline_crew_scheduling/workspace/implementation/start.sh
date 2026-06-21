#!/usr/bin/env bash
# Foreground launcher. The per-test-server isolation restarts this script
# before every pytest test, so the boot path is on the hot path and must be
# fast — skip pip when Flask is already importable for the running python3.
set -euo pipefail
cd "$(dirname "$0")"

if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

exec python3 app.py
