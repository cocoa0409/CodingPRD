#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only once — start.sh is re-run before every per-test reboot
# (8 rounds concurrently on a shared host); an extra interpreter start per
# boot widens the restart-poll window and surfaces as flaky
# "could not be restarted" timeouts under host load.
if [ ! -f .deps_installed ]; then
  python3 -m pip install -q -r requirements.txt
  touch .deps_installed
fi
exec python3 app.py
