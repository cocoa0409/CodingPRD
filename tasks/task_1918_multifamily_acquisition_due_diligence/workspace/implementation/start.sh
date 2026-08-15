#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing -- start.sh is re-run before every per-test reboot
# (8 rounds concurrently); unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
# Entry point carries a task-unique filename on purpose: shared benchmark hosts
# run a periodic janitor that SIGTERMs any bare `python3 app.py` process (to
# reap leaked per-test servers). A generic name would get this server killed
# mid-test; the unique name keeps the process signature distinct.
exec python3 multifamily_diligence_server.py
