#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# The dependency install is guarded so it is a no-op once flask is present.
# start.sh is re-invoked before EVERY per-test reboot and the stability sweep
# runs those reboots concurrently, so an unconditional pip install here would
# push boot past the runner's restart window and surface as flaky
# "could not be restarted" failures.  A find_spec probe is used instead of a
# full import because it is an order of magnitude faster to start.
if ! python3 -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('flask') else 1)" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

exec python3 app.py
