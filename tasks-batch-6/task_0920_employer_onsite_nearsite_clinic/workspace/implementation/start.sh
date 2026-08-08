#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Install only when missing -- start.sh is re-invoked before every per-test
# server reboot, and an unconditional pip install here would contend badly
# during the concurrent stability sweep.
# The probe only LOCATES the module rather than importing it: find_spec costs
# ~0.02s where `import flask` costs ~0.24s, and the saving is paid back on
# every one of the hundreds of boots per-test-server isolation performs.
if ! python3 -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('flask') else 1)" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

export PYTHONUNBUFFERED=1
export PORT="${PORT:-10000}"
exec python3 app.py
