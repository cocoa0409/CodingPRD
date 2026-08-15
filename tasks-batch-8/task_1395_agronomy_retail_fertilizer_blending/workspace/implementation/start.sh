#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# This host runs many benchmark pipelines concurrently; their runners can
# SIGTERM a recycled PID that now belongs to this server. The per-test
# isolation path kills listeners with SIGKILL (kill -9), which cannot be
# trapped, so ignoring SIGTERM here does not impede restarts — it only
# absorbs foreign stray SIGTERMs. Disposition is inherited across exec.
trap '' TERM
# Single python startup: app.py self-installs requirements on fresh hosts and
# re-execs. One interpreter per reboot keeps per-test restart latency minimal
# under concurrent sweep load.
exec python3 app.py
