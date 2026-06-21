#!/usr/bin/env bash
# Robust foreground launcher for the PRD-bench Flask app.
# - Serves the existing Flask `app` via waitress (a production-grade pure-Python
#   WSGI server) instead of the Werkzeug dev server. Waitress binds the socket
#   before accepting, handles concurrent connections, and exits cleanly on
#   SIGTERM -- which eliminates the boot/bind race and dropped-connection
#   (BadStatusLine) symptoms seen under the parallel per-test-server sweep.
# - Runs in the FOREGROUND via `exec` so signals propagate and the runner can
#   kill it cleanly between tests.
# - Installs deps only when missing (fast, deterministic boot; no reinstall churn).
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-10000}"
export PORT

# Only install dependencies when a required import is missing. This keeps boot
# fast and deterministic under the rapid restart load, while still provisioning
# a truly fresh environment.
if ! python3 -c "import flask, waitress" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

exec python3 app.py
