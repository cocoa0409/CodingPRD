#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Per-test-server isolation restarts this script before EVERY test, and the
# runner's per-test restart budget is only ~15s. To keep every boot well inside
# that budget (even under heavy host contention), the dependency install is
# done once, out-of-band, the FIRST time start.sh runs, recorded by a marker
# file. Subsequent boots skip straight to `exec python3 app.py` with no extra
# subprocess fork, so the only work per restart is the Flask import + bind.
MARKER=".deps_installed"
if [ ! -f "$MARKER" ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  : > "$MARKER"
fi
exec python3 app.py
