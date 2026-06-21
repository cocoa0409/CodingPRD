#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Dependencies are ensured at most once, gated by a marker file. start.sh is
# re-run before every per-test reboot (and the 8-round sweep runs them
# concurrently, sharing this directory), so spawning a Python import-probe on
# every boot adds ~500 redundant interpreter startups per sweep — the main
# boot-latency source behind flaky "could not be restarted" timeouts under
# cross-pipeline CPU contention. The marker is a launcher build artifact (no
# business state); per-test in-memory state is still wiped by the reboot.
MARKER=".deps_ok"
if [ ! -f "$MARKER" ]; then
  if ! python3 -c "import flask, waitress" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  : > "$MARKER"
fi
exec python3 app.py
