#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing -- start.sh is re-run before every per-test reboot;
# an unconditional pip install here causes boot-time contention.
# find_spec locates the package without executing its import machinery, which
# keeps the probe an order of magnitude cheaper than "import flask" on a busy host.
if ! python3 -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('flask') else 1)" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi
exec python3 serve.py
