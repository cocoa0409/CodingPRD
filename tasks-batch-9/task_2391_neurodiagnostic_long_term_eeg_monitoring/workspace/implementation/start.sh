#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# serve.py checks for Flask in-process and only pip-installs when it is missing,
# so a reboot costs exactly one interpreter launch.  PORT selects the listener.
exec python3 serve.py
