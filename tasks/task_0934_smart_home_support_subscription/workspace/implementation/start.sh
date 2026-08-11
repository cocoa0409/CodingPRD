#!/usr/bin/env bash
# Launcher for the Smart-Home Support Subscription API.
#
# G5: the dependency install is PROBED, never unconditional.  The harness runs
# `prd-bench-local-run --isolation per-test-server`, which re-invokes this
# script before every single pytest test (112 tests x 8 rounds); an
# unconditional `pip install` would multiply boot latency by hundreds and turn
# into flaky "API server could not be restarted" errors.
set -euo pipefail
cd "$(dirname "$0")"

if ! python3 -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('flask') else 1)" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

exec python3 app.py
