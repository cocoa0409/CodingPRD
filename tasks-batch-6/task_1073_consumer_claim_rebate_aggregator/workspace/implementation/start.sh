#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot;
# an unconditional pip install would cause boot-time contention under the
# concurrent stability sweep and show up as flaky restart timeouts.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py
