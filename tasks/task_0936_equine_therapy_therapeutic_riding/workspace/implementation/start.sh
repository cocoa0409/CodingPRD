#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Dependency guard: start.sh is re-invoked before EVERY per-test server reboot
# under `--isolation per-test-server`.  An unconditional `pip install` there
# costs seconds per boot and shows up as flaky "could not be restarted"
# failures, so probe for the module instead and only install when missing.
if ! python3 -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('flask') else 1)" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt >/dev/null 2>&1 || true
fi

exec python3 app.py
