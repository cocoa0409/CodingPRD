#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (rounds run concurrently); an unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts.
# The probe uses importlib.util.find_spec rather than a real import: importing
# Flask costs ~0.3s of CPU and this probe runs on every one of the ~100 reboots
# a per-test-server run performs, which is pure boot latency (and, on a busy
# host, a slow boot is indistinguishable from a dead server).
if ! python3 -c "import importlib.util as u, sys; sys.exit(0 if u.find_spec('flask') and u.find_spec('waitress') else 1)" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt \
    || python3 -m pip install -q --break-system-packages -r requirements.txt \
    || true
fi
# The entry module is deliberately NOT called app.py: this host runs many
# unrelated API servers at once and a stray `pkill -f "python3 app.py"` from a
# neighbouring process tree would otherwise take this server down mid-request.
exec python3 plant_assembly_api.py
