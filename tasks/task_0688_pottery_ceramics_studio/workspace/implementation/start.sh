#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# start.sh is re-run before EVERY per-test reboot, 8 rounds concurrently. Boot
# time is on the critical path of the runner's 15s restart-poll window, so this
# script must do as little as possible on the hot path.
#
# Dependency install is gated behind a sentinel file rather than an `import flask`
# probe: the probe spawns a full extra Python interpreter (cold-import cost) on
# every single restart, doubling per-restart startup work and pushing boots past
# the restart-poll window under the concurrent sweep, which surfaces as flaky
# "could not be restarted" failures. The sentinel makes the steady-state path a
# pure file test with no interpreter spawn.
SENTINEL=".deps_installed"
if [ ! -f "$SENTINEL" ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch "$SENTINEL"
fi
exec python3 app.py
