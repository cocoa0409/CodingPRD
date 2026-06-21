#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when the framework is missing — start.sh is re-run before every
# per-test reboot under `--isolation per-test-server` (8 stability rounds run
# those reboots concurrently). An unconditional `pip install` on every boot
# causes network/disk contention and flaky "could not be restarted" timeouts,
# so we probe importability first and skip the install when deps are present.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py
