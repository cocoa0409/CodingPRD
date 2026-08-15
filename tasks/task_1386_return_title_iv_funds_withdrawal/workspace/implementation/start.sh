#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Boot tracing: append a timestamped line per stage so that "could not be
# restarted" flakes under the concurrent sweep can be attributed (slow pip
# check vs slow interpreter start vs killed-while-booting). Diagnostics only;
# no behavior change.
BOOT_LOG="${BOOT_LOG:-/tmp/r2t4_boot_${PORT:-noport}.log}"
echo "$(date +%H:%M:%S.%N) start.sh enter pid=$$" >> "$BOOT_LOG" || true
# Install only when missing — start.sh is re-invoked before every per-test
# reboot (8 rounds concurrently); unconditional pip install here causes
# boot-time contention and flaky "could not be restarted" timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  echo "$(date +%H:%M:%S.%N) pip install path taken pid=$$" >> "$BOOT_LOG" || true
  python3 -m pip install -q -r requirements.txt
fi
echo "$(date +%H:%M:%S.%N) exec app.py pid=$$" >> "$BOOT_LOG" || true
exec python3 app.py
