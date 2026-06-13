#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Dependency install is guarded so it runs at most once. start.sh is re-invoked
# before every per-test reboot (8 rounds concurrently under the stability sweep);
# an unconditional `pip install` — or even a per-boot `python3 -c "import flask"`
# probe that spawns a fresh interpreter every time — adds boot-time CPU
# contention that can flake as "could not be restarted". A filesystem sentinel
# lets every reboot after the first skip straight to exec with no extra process
# spawn. The sentinel is a build artifact, not application/entity state, so it
# does not violate the in-memory-only storage rule.
SENTINEL=".deps_installed"
if [ ! -f "$SENTINEL" ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch "$SENTINEL"
fi
exec python3 app.py
