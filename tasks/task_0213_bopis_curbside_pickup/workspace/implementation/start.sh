#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Dependency guard. start.sh is re-invoked before EVERY per-test reboot, and the
# stability sweep runs 8 rounds concurrently, so boot-time CPU contention is the
# scarce resource. An unconditional `pip install` here serializes badly; even a
# per-boot `python3 -c "import flask"` import-probe spawns a full extra
# interpreter on every one of the hundreds of reboots, which under 8x saturation
# is enough to push an occasional boot past the runner's 15s readiness window
# ("could not be restarted").
#
# So: install once, drop a sentinel, and on every subsequent boot skip the extra
# interpreter entirely — go straight to exec. The sentinel is a build artifact,
# not application state (no entity data), so it does not violate the in-memory
# storage contract; server state is still wiped on every reboot.
SENTINEL=".deps_ok"
if [ ! -f "$SENTINEL" ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  : > "$SENTINEL"
fi
exec python3 app.py
