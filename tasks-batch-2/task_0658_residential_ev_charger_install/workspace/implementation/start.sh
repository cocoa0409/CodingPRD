#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Dependencies are installed at most once. start.sh is re-run before every
# per-test reboot (and 8 rounds run concurrently), so the hot path must avoid
# spawning an extra Python interpreter just to probe for Flask: that probe,
# multiplied across hundreds of concurrent boots, saturates CPU and produces
# flaky "could not be restarted" readiness timeouts. We gate the install on a
# cheap filesystem sentinel instead; `test -f` costs nothing.
SENTINEL=".deps_installed"
if [ ! -f "$SENTINEL" ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch "$SENTINEL"
fi
exec python3 app.py
