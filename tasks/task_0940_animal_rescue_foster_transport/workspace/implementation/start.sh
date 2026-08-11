#!/usr/bin/env bash
# Launcher for the Animal Rescue & Foster/Transport Network API.
#
# The harness runs `prd-bench-local-run --isolation per-test-server`, which
# kill -9's the previous server and immediately re-invokes this script before
# EVERY pytest test.  Two consequences shape this file:
#
#   1. Dependency installation must be a cheap no-op once the deps are present.
#      We probe with importlib.util.find_spec (a few ms) instead of invoking
#      pip (hundreds of ms, and pathological under concurrent sweeps).
#   2. app.py pre-binds the listening socket itself with SO_REUSEADDR in an
#      EADDRINUSE-tolerant, time-bounded retry loop, because the replacement
#      server races the dying socket of the process the harness just killed.
set -euo pipefail
cd "$(dirname "$0")"

if ! python3 -c 'import importlib.util, sys; sys.exit(0 if importlib.util.find_spec("flask") and importlib.util.find_spec("werkzeug") else 1)' >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

exec python3 app.py
