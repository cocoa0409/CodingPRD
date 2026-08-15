#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test
# reboot; unconditional pip install here causes boot-time contention.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
LOG="${BOOT_LOG:-/dev/null}"
echo "$(date -u +%T.%N) boot (port ${PORT:-10000}, pid $$)" >>"$LOG"
exec python3 app.py 2>>"$LOG"
