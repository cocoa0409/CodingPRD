#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Dependency bootstrap is handled inside app.py (a single import attempt with a
# one-time pip install fallback), so there is NO extra interpreter spawn per
# boot here. start.sh is re-run before every per-test reboot (8 rounds
# concurrently); keeping this script to a single exec keeps boot latency low and
# avoids the "could not be restarted" contention seen when each boot also forks
# an extra `python3 -c "import flask"` probe.
exec python3 app.py
