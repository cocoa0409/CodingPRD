#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only once — start.sh is re-run before every per-test reboot (many
# rounds concurrently on a shared host); a per-boot python import probe costs
# a full interpreter+flask startup each time and causes boot-time contention
# and flaky "could not be restarted" timeouts.
if [ ! -f .deps_installed ]; then
  python3 -m pip install -q -r requirements.txt
  touch .deps_installed
fi
exec python3 app.py
