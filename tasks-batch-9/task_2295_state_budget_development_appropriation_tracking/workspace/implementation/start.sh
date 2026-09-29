#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# No dependency probe here.  start.sh is re-invoked before every per-test server
# reboot, and `python3 -c "import flask"` costs a full flask import (3-7s on a
# loaded host), which doubled boot time for every single test.  app.py installs
# requirements.txt and re-execs itself if flask is genuinely missing, so the
# happy path is a single interpreter start.
exec python3 app.py
