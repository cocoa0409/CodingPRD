#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install deps once into a sentinel-guarded marker so per-test restarts skip the
# (slow, possibly-networked) pip step entirely. Avoids spawning an extra Python
# interpreter just to probe importability, which is expensive under CPU contention.
if [ ! -f .deps_installed ]; then
  python3 -m pip install -q -r requirements.txt && touch .deps_installed
fi

# Under per-test-server isolation the evaluator kills the previous server and
# immediately re-runs start.sh. On macOS a freshly killed listener can leave the
# TCP port transiently bound, so a naive bind() races and the new process dies
# with EADDRINUSE. Free any stale listener on $PORT and wait until the port is
# actually bindable before handing off to the app, so every restart succeeds.
PORT="${PORT:-10000}"
for _ in $(seq 1 50); do
  pids=$(lsof -ti:"$PORT" -sTCP:LISTEN 2>/dev/null || true)
  if [ -n "$pids" ]; then
    kill -9 $pids 2>/dev/null || true
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
