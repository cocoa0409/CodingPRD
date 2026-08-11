#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Straight to the interpreter: app.py claims the listening socket before it
# imports Flask and before it checks/installs dependencies, which keeps the
# port-exposure window between the harness's SIGKILL of the previous server and
# our bind() as short as possible.  (See the app.py module docstring.)
exec python3 app.py
