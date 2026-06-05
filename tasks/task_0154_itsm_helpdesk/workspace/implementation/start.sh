#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (per-test-server isolation). The per-test restart budget is only ~15s and an
# 8x-parallel sweep boots many interpreters at once, so the hot path must avoid
# spawning an extra python3 just to probe for flask. Use a filesystem sentinel:
# the dependency check (and any pip install) runs exactly once, then every
# subsequent reboot skips straight to exec with no probe interpreter.
SENTINEL="$(dirname "$0")/.deps_ok"
if [ ! -f "$SENTINEL" ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch "$SENTINEL"
fi
exec python3 app.py
