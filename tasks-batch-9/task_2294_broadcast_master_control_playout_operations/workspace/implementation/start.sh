#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# mcr_playout_api.py installs requirements.txt and re-execs itself if Flask is
# missing, so a reboot pays for exactly one interpreter start. start.sh is re-run
# before every per-test reboot, and every extra process here is boot latency the
# harness waits on.
#
# The entry module is deliberately NOT named app.py: this host runs many unrelated
# API servers at once and a stray `pkill -f "python3 app.py"` from a neighbouring
# process tree would otherwise take this server down mid-request.
exec python3 mcr_playout_api.py
