#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# start.sh is re-invoked before every per-test reboot (isolation
# per-test-server), hundreds of times per sweep. Pay the dependency probe
# once (sentinel on disk) instead of a full extra CPython startup per boot:
# every spared interpreter boot widens the margin against the runner's
# restart-poll window under the concurrent 8-round sweep.
if [ ! -f .deps_installed ] || [ requirements.txt -nt .deps_installed ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch .deps_installed
fi
exec python3 app.py
