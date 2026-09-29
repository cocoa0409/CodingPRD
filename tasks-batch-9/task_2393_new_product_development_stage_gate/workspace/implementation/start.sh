#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently); an unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts.
# The probe only *locates* Flask (find_spec) instead of importing it: on a
# loaded host importing werkzeug/jinja costs seconds, and paying it twice per
# reboot would eat into the harness's start-up window.
if ! python3 -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('flask') else 1)" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 app.py
