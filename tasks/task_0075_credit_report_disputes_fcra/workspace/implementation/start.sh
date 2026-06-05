#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install dependencies only when missing. start.sh is re-invoked before every
# test under per-test-server isolation; running pip on every boot adds network
# latency that can blow the restart timeout under concurrent load.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py
