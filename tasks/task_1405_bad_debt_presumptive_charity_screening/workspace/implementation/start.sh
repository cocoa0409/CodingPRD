#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# start.sh is re-run before every per-test reboot (8 rounds concurrently), and
# each boot must complete well inside the runner's restart-poll window even
# under heavy multi-tenant host load. Spawning an extra interpreter per boot
# (`python3 -c "import flask"` guard) roughly doubles boot cost, so the
# dependency check is memoized by a marker file after its first success.
# The marker records only "dependencies verified" — no API state — so
# per-test isolation is unaffected.
if [ ! -f .deps_installed.marker ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  touch .deps_installed.marker
fi
exec python3 app.py
