#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently); an unconditional pip install on every boot causes
# boot-time contention and flaky "could not be restarted" timeouts.
#
# We guard on a marker file rather than spawning a `python3 -c "import flask"`
# probe each boot: under the concurrent stability sweep, every avoided
# interpreter spawn shaves CPU off a saturated host and keeps the boot well
# inside the runner's restart-poll window. The marker is written only after a
# successful install, so a half-installed env still re-installs.
MARKER=".deps_installed"
if [ ! -f "$MARKER" ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch "$MARKER"
fi
exec python3 app.py
