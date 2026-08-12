#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently); unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts. A sentinel file
# avoids paying an extra interpreter boot for the import check on every
# restart: the check runs once per host, then only `exec python3 app.py`.
SENTINEL="${HOME}/.cache/task_1182_deps_ok"
if [ ! -f "$SENTINEL" ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  mkdir -p "$(dirname "$SENTINEL")"
  touch "$SENTINEL"
fi
exec python3 app.py
