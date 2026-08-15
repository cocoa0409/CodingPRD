#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently); unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
# Entry point is deliberately NOT named app.py: this host runs many benchmark
# pipelines concurrently, and neighboring cleanup scripts pattern-kill
# "app.py" processes. A task-unique name keeps those sweeps from SIGTERMing
# this server mid-round.
exec python3 bit1973_server.py
