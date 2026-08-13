#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Dependency check writes a .deps_ok marker on first verified boot; steady-state
# reboots skip the duplicate `python3 -c "import flask"` interpreter spawn,
# halving per-boot cost. The harness re-runs start.sh before every per-test
# reboot (8 rounds concurrently), so per-boot cost matters. The marker is boot
# metadata only — no entity data.
if [ ! -f .deps_ok ] || [ requirements.txt -nt .deps_ok ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch .deps_ok
fi
exec python3 app.py
