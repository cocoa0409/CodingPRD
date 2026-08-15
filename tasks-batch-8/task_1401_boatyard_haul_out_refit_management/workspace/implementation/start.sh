#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing -- start.sh is re-run before every per-test reboot
# (rounds run concurrently); unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts.
if [ ! -f .deps_ok ]; then
  # First boot only: verify deps once (single interpreter start), install if
  # missing, then record a sentinel so every per-test reboot goes straight to
  # exec -- halving boot-time interpreter starts under the 8-round sweep.
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch .deps_ok
fi
exec python3 app.py
