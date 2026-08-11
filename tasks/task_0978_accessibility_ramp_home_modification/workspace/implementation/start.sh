#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently); unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts. A stamp file avoids
# even the `import flask` probe interpreter once deps are known to be present,
# minimizing per-restart CPU so the readiness window is met under 8x load.
STAMP=".deps_installed"
if [ ! -f "$STAMP" ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch "$STAMP"
fi
export PYTHONDONTWRITEBYTECODE=1
echo "$(date +%s.%N) spawn pid=$$ port=${PORT:-?}" >> boot_trace.log
exec python3 app.py
