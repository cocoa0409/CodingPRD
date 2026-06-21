#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Install deps only when Flask is missing. start.sh is re-invoked before every
# per-test reboot (8 rounds run concurrently); an unconditional pip install here
# causes boot-time contention and flaky "could not be restarted" timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

# Under per-test-server isolation the evaluator kills the previous server and
# immediately re-runs start.sh. A freshly killed listener can leave the TCP port
# transiently bound, so free any stale listener and wait until the port is
# bindable before handing off (avoids same-port bind-race flakes).
PORT="${PORT:-10000}"
for _ in $(seq 1 50); do
  if command -v lsof >/dev/null 2>&1; then
    pids=$(lsof -ti:"$PORT" -sTCP:LISTEN 2>/dev/null || true)
    if [ -n "$pids" ]; then
      kill -9 $pids 2>/dev/null || true
    fi
  fi
  if python3 - "$PORT" <<'PYBIND' 2>/dev/null
import socket, sys
p = int(sys.argv[1])
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(("0.0.0.0", p))
finally:
    s.close()
PYBIND
  then
    break
  fi
  sleep 0.1
done

exec python3 app.py
