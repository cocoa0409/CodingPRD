#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Guard the dependency install with a sentinel so per-test reboots
# (per-test-server isolation re-runs start.sh before every test, and the
# stability sweep runs those reboots concurrently) do NOT re-run pip every
# time — an unconditional install causes boot-time contention and flaky
# "could not be restarted" timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

# Bind 0.0.0.0:$PORT (default 10000) in the foreground; exec so signals
# propagate to the server process. app.py performs a defensive bind-retry
# loop in case the just-killed previous server briefly still holds the port.
exec python3 app.py
