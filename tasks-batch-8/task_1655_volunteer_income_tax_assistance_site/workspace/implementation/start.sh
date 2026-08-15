#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently); unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
# The serving process must not match the host-wide `pkill -f 'python3 app.py'`
# cleanup patterns used by unrelated tooling on shared hosts: keep the module
# name task-specific. The evaluator contract is unchanged (`bash start.sh`).
exec python3 vita_site_ops_server.py
