#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before EVERY per-test reboot,
# and the 8-round stability sweep runs those reboots concurrently. An
# unconditional pip install (or even an unconditional `python3 -c import`
# probe) on every boot adds interpreter-startup contention that can push the
# boot past the runner's restart window, surfacing as flaky
# "could not be restarted" / setup-timeout failures.
#
# Fast path: once deps are confirmed present we drop a sentinel and skip the
# probe interpreter entirely on subsequent reboots, so the steady-state reboot
# spawns exactly ONE python process (the server).
if [ ! -f .deps_ok ]; then
  if ! python3 -c "import flask, waitress" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  # Sentinel write is best-effort: a read-only cwd must not abort startup.
  : > .deps_ok 2>/dev/null || true
fi
exec python3 app.py
