#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Dependency check: the first boot verifies flask is importable (installing it
# if missing) and records that in a marker file; later boots skip the check.
# start.sh is re-run before every per-test reboot (8 sweep rounds
# concurrently), and the naive `python3 -c "import flask"` guard pays a full
# interpreter + flask import per boot — doubling boot cost and pushing boots
# past the runner's restart-poll window under parallel load. Unconditional
# pip install is worse (boot-time contention).
if [ ! -f .deps_ok ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch .deps_ok
fi
exec python3 app.py
