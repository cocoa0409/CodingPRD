#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing. start.sh is re-run before every per-test reboot
# (per-test-server isolation); an unconditional pip install on every boot would
# cause contention under the 8x-parallel stability sweep and surface as flaky
# "could not be restarted" timeouts. Use a filesystem sentinel so the dependency
# check (and any pip install) runs exactly once, then subsequent reboots skip
# straight to exec.
SENTINEL="$(dirname "$0")/.deps_ok"
if [ ! -f "$SENTINEL" ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch "$SENTINEL"
fi
exec python3 app.py
