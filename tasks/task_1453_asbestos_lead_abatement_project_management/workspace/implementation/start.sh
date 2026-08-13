#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently); unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
# The entry filename is deliberately task-unique: co-tenant pipelines on this
# shared host run `pkill -f "python3 app.py"`, which would otherwise SIGTERM
# this server mid-sweep and surface as spurious per-test connection resets.
exec python3 asbestos_abatement_server.py
