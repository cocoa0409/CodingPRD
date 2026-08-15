#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently); unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
# Entry module is deliberately NOT named app.py: co-tenant benchmark pipelines
# on this shared host run `pkill -f "python3 app.py"` as sweep cleanup, which
# mass-kills every task's server mid-test and surfaces as flaky connection
# resets. A task-unique module name keeps this server out of that blast radius.
exec python3 pharmacy_claim_adjudication_server.py
