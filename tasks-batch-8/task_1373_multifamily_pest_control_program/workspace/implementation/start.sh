#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# server_launch.py binds $PORT first (see its docstring for the EADDRINUSE
# rationale), verifies flask is importable (pip-installing only if missing),
# then execs app.py on the pre-bound socket.
exec python3 server_launch.py
