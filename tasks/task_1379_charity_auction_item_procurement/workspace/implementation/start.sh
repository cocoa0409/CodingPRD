#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Single-interpreter boot: a separate `python3 -c "import flask"` preflight
# doubles interpreter startup on every per-test reboot (8 rounds
# concurrently) and contributed to flaky "could not be restarted" timeouts.
# find_spec() answers the dependency question without importing flask.
exec python3 - <<'PYEOF'
import importlib.util
import runpy
import subprocess
import sys

if importlib.util.find_spec("flask") is None:
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"]
    )

runpy.run_path("app.py", run_name="__main__")
PYEOF
