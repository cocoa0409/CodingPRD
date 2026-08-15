#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# app.py performs the dependency check itself (fast find_spec probe) and binds
# $PORT before importing Flask, minimizing the free-port window between the
# runner's per-test kill and our bind (a foreign ephemeral connection grabbing
# the port in that gap blocks the bind for ~60s via TIME-WAIT).
exec python3 app.py
