#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Dependencies are installed exactly once and then recorded with a sentinel file.
# start.sh is re-invoked before EVERY per-test reboot (78 tests x 8 concurrent
# rounds); spawning a `python3 -c "import flask"` probe on each of those boots
# adds an interpreter spawn that competes for CPU under the 8x concurrent load
# and lengthens boot latency, which is exactly what triggers the runner's
# "could not be restarted" timeout. A cheap filesystem sentinel check avoids the
# extra interpreter spawn on the hot path while still installing on first boot.
SENTINEL=".deps_installed"
if [ ! -f "$SENTINEL" ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch "$SENTINEL"
fi
exec python3 app.py
