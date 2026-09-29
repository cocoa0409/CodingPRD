#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing -- start.sh is re-run before every per-test reboot
# (rounds run concurrently); an unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts.
#
# The probe uses find_spec rather than `import flask` so it does not pay for
# pulling in werkzeug/jinja2/click on every one of the ~183 reboots a round
# performs -- that import roughly doubled boot latency, widening the window in
# which a request can arrive before the new process has bound its port.
if ! python3 -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('flask') else 1)" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py
