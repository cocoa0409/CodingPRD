#!/usr/bin/env bash
set -euo pipefail
# Resolve this script's own directory absolutely so the server boots correctly
# no matter what cwd the (re)start is invoked from — the per-test-server runner
# restarts via this script before every test and may not preserve cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$SCRIPT_DIR"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently); unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py
