#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Install only when missing: start.sh is re-invoked before EVERY per-test reboot
# and an unconditional pip install turns those reboots into contended installs
# that blow past the runner's restart window.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

exec python3 app.py
