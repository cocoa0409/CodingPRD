#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Install only when missing — start.sh is re-invoked before every per-test
# server reboot, so an unconditional pip install would contend and time out.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

export PORT="${PORT:-10000}"

# exec, so the python server replaces this shell: the runner reaps the server
# between tests by SIGKILLing the PID holding the listening socket, and a
# surviving wrapper shell would leak a process on every one of those reboots.
exec python3 app.py
