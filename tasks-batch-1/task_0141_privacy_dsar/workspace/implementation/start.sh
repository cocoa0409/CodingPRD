#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Install dependencies only when missing. start.sh is re-invoked before every
# per-test server reboot, and the stability sweep runs those reboots
# concurrently; an unconditional `pip install` on every boot creates boot-time
# contention that shows up as flaky "could not be restarted" timeouts. Guard on
# a cheap import of the framework so the install is a no-op once present.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

# Foreground exec so signals propagate; app.py reads $PORT and binds 0.0.0.0.
exec python3 app.py
