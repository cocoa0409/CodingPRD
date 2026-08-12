#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Install only when missing.  start.sh is re-invoked before every per-test
# reboot under `--isolation per-test-server`; an unconditional pip install here
# causes boot-time contention and flaky "could not be restarted" timeouts.
# The probe uses `find_spec` rather than a full `import flask`: importing flask
# costs ~250 ms of pure interpreter work, paid on every single reboot, which is
# a large fraction of the harness's restart budget under a concurrent sweep.
if ! python3 -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('flask') else 1)" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

# exec so no orphan parent squats the port and signals propagate.
exec python3 app.py
