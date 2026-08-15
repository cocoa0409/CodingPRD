#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Dependencies are verified/installed once per host, recorded by a sentinel.
# start.sh is re-run before every per-test reboot (8 sweep rounds
# concurrently); a per-boot `python3 -c "import flask, waitress"` costs a full
# interpreter spawn (~0.3s idle, several seconds under sweep load) and a per-
# boot pip invocation is worse. The sentinel keeps every reboot on the fastest
# possible path. The sentinel is dependency bookkeeping only — all application
# state stays in-memory, so per-test reboots still start from a blank slate.
SENTINEL=/tmp/.task_1315_deps_ok
if [ ! -f "$SENTINEL" ]; then
  if ! python3 -c "import flask, waitress" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt || \
      python3 -m pip install -q --user --break-system-packages -r requirements.txt
  fi
  touch "$SENTINEL"
fi
# App stderr goes to a per-port log so a crash during a benchmark run is
# diagnosable after the fact (the runner's per-test respawn discards it).
# Pure redirection: no extra process, no state, no behavior change.
exec python3 app.py 2>>"/tmp/.task_1315_server_${PORT:-0}.log"
