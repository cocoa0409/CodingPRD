#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Exactly one process spawn per boot. Dependency install is handled inside
# app.py only when the import fails, so the hot per-test reboot path (8 rounds
# concurrently restart the server before every test) never spawns an extra
# pre-flight interpreter — that subprocess churn is what causes boot-time
# "could not be restarted" timeouts under peak contention.
exec python3 app.py
