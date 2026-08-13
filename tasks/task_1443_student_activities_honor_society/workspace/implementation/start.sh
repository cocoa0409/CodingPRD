#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — the harness re-runs start.sh before every
# per-test reboot; unconditional pip install causes boot-time contention.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
# Launch with an absolute, task-unique script path so the process argv never
# matches broad pattern kills (`pkill -f "python3 app.py"` / `pkill -f app.py`)
# that co-tenant benchmark pipelines on this shared host run mid-sweep.
exec python3 "$PWD/honor_society_server.py"
