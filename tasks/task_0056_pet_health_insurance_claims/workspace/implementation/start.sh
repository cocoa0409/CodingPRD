#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Only install when Flask is missing. Under per-test-server isolation the server
# is restarted before every test; running pip on each restart can push boot past
# the restart timeout intermittently.
python3 -c "import flask" 2>/dev/null || python3 -m pip install -q -r requirements.txt
exec python3 app.py
