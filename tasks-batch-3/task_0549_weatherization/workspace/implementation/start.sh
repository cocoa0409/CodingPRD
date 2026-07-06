#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Install dependencies only when missing. start.sh is re-invoked before every
# per-test server reboot (concurrently across stability rounds); an
# unconditional pip install here would cause boot-time contention and flaky
# "could not be restarted" timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

# Run the server in the FOREGROUND. It reads $PORT from the environment
# (default 10000) and binds 0.0.0.0 (see app.py). exec so signals propagate.
exec python3 app.py
