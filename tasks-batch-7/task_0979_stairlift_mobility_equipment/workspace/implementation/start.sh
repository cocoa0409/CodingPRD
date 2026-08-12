#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Single-interpreter boot: app.py self-installs flask only if the import fails,
# so the common path spawns exactly one python process. Under per-test-server
# isolation start.sh is re-run before every test, and during the 8-way
# concurrent stability sweep the extra interpreter for a separate import check
# measurably inflates boot latency on a saturated host (the runner's restart
# poll window is finite).
exec python3 app.py
