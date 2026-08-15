#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Single-interpreter boot: check for flask via find_spec (no module execution,
# ~4x faster than `import flask`) and exec app.py from the same process.
# start.sh is re-run before every per-test reboot (8 rounds concurrently on a
# shared host); every shaved millisecond shortens the restart window in which
# a host-wide scheduling stall can trip the runner's 15s readiness poll.
exec python3 -c "
import importlib.util, os, subprocess, sys
if importlib.util.find_spec('flask') is None:
    subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-q', '-r', 'requirements.txt'])
os.execv(sys.executable, [sys.executable, 'app.py'])
"
