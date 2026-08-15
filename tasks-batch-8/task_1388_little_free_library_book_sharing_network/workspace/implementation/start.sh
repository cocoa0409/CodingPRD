#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently); unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts.
if ! python3 -c "import flask, waitress" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt || \
    python3 -m pip install -q --user --break-system-packages -r requirements.txt
fi
# NOTE: the entry module is deliberately NOT named app.py — on this shared
# host, sibling benchmark pipelines occasionally run `pkill -f "python3
# app.py"` as cleanup, which mass-kills every task's server mid-sweep.
# A task-unique module name keeps this server out of that blast radius.
exec python3 library_network_server.py
