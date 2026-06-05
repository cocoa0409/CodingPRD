#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Install dependencies only when missing. The test harness re-invokes start.sh
# before EVERY per-test server restart (and runs the stability sweep
# concurrently); an unconditional `pip install` on every boot causes
# boot-time contention that surfaces as flaky "could not be restarted"
# timeouts. Guard on a cheap import probe of the framework.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

exec python3 app.py
