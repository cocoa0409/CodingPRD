#!/usr/bin/env bash
cd "$(dirname "$0")"
# Under per-test-server isolation start.sh runs before EVERY test (hundreds of
# boots, x8 concurrent during the stability sweep). Any extra interpreter spawn
# before the server starts adds CPU contention that can push boot past the
# runner's restart-poll window and surface as a spurious "could not be
# restarted" setup error. So we do dependency installation exactly once (cold
# start) gated behind a filesystem marker -- zero subprocesses on warm restarts.
if [ ! -f .deps_installed ]; then
  python3 -m pip install -q -r requirements.txt && touch .deps_installed
fi
exec python3 app.py
