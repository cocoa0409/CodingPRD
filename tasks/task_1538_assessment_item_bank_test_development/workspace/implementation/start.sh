#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently); unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
# Entry file is deliberately NOT named app.py: sibling pipeline processes on
# this shared host aggressively `pkill -f "python3 app.py"` between sweep
# waves, which kills the server mid-test and surfaces as spurious connection
# resets / restart failures.
exec python3 itembank_server.py
