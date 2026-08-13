#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (isolation per-test-server); unconditional pip install here would cause
# boot-time contention and flaky restart timeouts. The sentinel file keeps the
# dependency check cheap after the first successful boot.
if [ ! -f .deps_installed ] || [ requirements.txt -nt .deps_installed ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch .deps_installed
fi
exec python3 app.py
