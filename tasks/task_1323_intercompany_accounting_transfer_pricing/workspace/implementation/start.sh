#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (rounds run concurrently); unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
# Skip .pyc writes: with 8 concurrent rounds rebooting the server per test,
# bytecode-write contention in __pycache__ adds boot latency for no benefit.
export PYTHONDONTWRITEBYTECODE=1
exec python3 -X utf8 app.py
