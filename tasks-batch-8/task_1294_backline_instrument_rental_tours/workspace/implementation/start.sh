#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently); unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
# Launch with an absolute script path so the process argv is unique to this
# task — broad pattern kills (e.g. `pkill -f "python3 app.py"`) from co-tenant
# pipelines on a shared host must not match this server mid-sweep.
exec python3 "$PWD/app.py"
