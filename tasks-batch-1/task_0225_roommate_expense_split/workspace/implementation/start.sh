#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Dependency install is guarded so the per-test-reboot hot path pays no extra
# subprocess cost. start.sh is re-invoked before every test under
# per-test-server isolation (8 rounds run concurrently); an unconditional pip
# install — or even a forked `python3 -c "import flask"` probe on every boot —
# adds contention that can push a boot past the runner's restart-poll window and
# surface as a spurious "could not be restarted". A filesystem sentinel records
# that deps are satisfied; after the first successful install we touch .deps_ok
# and every subsequent reboot skips the probe entirely.
if [ ! -f .deps_ok ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch .deps_ok
fi
exec python3 app.py
