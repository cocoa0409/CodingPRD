#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install deps once (marker file) — start.sh is re-run before every per-test
# reboot, and spawning an extra python interpreter per boot adds latency that
# can push startup past the runner's restart-poll window under parallel load.
if [ ! -f .deps_ok ]; then
  python3 -m pip install -q -r requirements.txt
  touch .deps_ok
fi
exec python3 app.py
