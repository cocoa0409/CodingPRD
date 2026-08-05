#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

export PORT="${PORT:-10000}"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1

# Install only when missing -- start.sh is re-run before every per-test reboot,
# and an unconditional pip install here causes boot-time contention and flaky
# "could not be restarted" timeouts when many reboots run concurrently.
if ! python3 -c "import flask" >/dev/null 2>&1; then
  python3 -m pip install -q -r requirements.txt
fi

# This host runs concurrent pipelines; a co-tenant load spike can make the very
# first import slow enough to look like a boot failure.  Probe the app module
# (import machinery only, no server) and retry briefly before handing off.
for attempt in 1 2 3 4 5 6 7 8 9 10; do
  if python3 -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('app') else 1)" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

exec python3 app.py
