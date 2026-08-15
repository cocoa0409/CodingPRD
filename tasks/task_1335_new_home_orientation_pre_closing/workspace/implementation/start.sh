#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (rounds run concurrently); unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts. A sentinel file caches
# the dependency probe so steady-state boots pay for exactly one python startup
# (the server itself) instead of two.
if [ ! -f .deps_ok ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch .deps_ok
fi
# server.py binds the listen socket before importing Flask (see that file).
# stderr is appended to a log because the runner spawns us with stderr
# discarded; genuine boot crashes must remain diagnosable.
exec python3 server.py 2>> .server_err.log
