#!/usr/bin/env bash
# Launch the Lead Service Line Inventory & Replacement API.
#
# The harness runs this script again before every individual test
# (--isolation per-test-server), so the happy path must be as cheap as
# possible: no probe subprocess, no unconditional `pip install` (which would
# thrash the index and cause "server could not be restarted" timeouts when
# several rounds boot at once).  app.py self-heals the one dependency it needs
# if -- and only if -- the import actually fails.
set -euo pipefail
cd "$(dirname "$0")"
exec python3 app.py
