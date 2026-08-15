#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Single-interpreter boot: the dependency check imports flask in the SAME
# python process that then runs app.py in-process (runpy), so each per-test
# restart pays for one python boot + one flask import instead of two.
# start.sh is re-invoked before every per-test reboot (8 sweep rounds
# concurrently); halving boot CPU cost shrinks the restart-poll failure
# window under host load. Install semantics are unchanged: flask is imported
# on every boot and pip-installed only when missing.
exec python3 - <<'PYEOF'
import runpy
import subprocess
import sys

try:
    import flask  # noqa: F401
except ImportError:
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"]
    )

runpy.run_path("app.py", run_name="__main__")
PYEOF
