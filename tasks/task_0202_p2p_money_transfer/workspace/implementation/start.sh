#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Dependency install is guarded so that the common per-test-reboot path pays NO
# extra subprocess cost. start.sh is re-invoked before every test under
# per-test-server isolation (8 rounds concurrently); an unconditional pip
# install — or even a `python3 -c "import flask"` probe that forks a second
# interpreter — adds boot-time contention that can push a boot past the runner's
# restart-poll window and surface as a spurious "could not be restarted".
#
# A filesystem sentinel records that deps are satisfied: after the first
# successful install we touch .deps_ok, and every subsequent reboot skips the
# probe entirely. The sentinel lives next to the source so a fresh checkout
# (no sentinel) still installs once.
if [ ! -f .deps_ok ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch .deps_ok
fi

# Hand off directly to python with no further subprocess work on the hot path.
# The runner already frees the port (kill_port) before invoking this script, and
# app.py retries the bind to absorb any lingering-socket race — so adding an
# lsof/kill here would only contend for CPU during the concurrent sweep without
# improving boot reliability.
exec python3 app.py
