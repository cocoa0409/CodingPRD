#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently); unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts. To avoid spawning an
# extra Python interpreter on every one of the hundreds of per-test reboots, we
# record a sentinel file after the first successful dependency check and skip
# the import probe entirely on subsequent boots. The sentinel lives outside the
# tracked source tree and only caches a (re)usable interpreter state; it never
# seeds any application data.
SENTINEL="${TMPDIR:-/tmp}/.prd_bench_0630_deps_ok"
if [ ! -f "$SENTINEL" ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  : > "$SENTINEL" 2>/dev/null || true
fi
exec python3 app.py
