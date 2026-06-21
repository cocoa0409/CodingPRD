#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install dependencies only when they are not already importable. Under
# per-test-server isolation the server is restarted before every test; running
# pip on every boot would serialize on the shared package cache and blow past
# the restart readiness window. The guard keeps first-boot install behavior
# while making subsequent restarts instant.
python3 -c "import flask" >/dev/null 2>&1 || python3 -m pip install -q -r requirements.txt
exec python3 app.py
