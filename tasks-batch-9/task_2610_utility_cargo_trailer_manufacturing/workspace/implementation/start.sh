#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-invoked before every per-test reboot
# (and 8 stability rounds run those reboots concurrently); an unconditional
# pip install here causes boot contention and flaky restart timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py
