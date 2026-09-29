#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
# Install only when missing — start.sh is re-run before every per-test reboot
# (8 rounds concurrently); an unconditional pip install here causes boot-time
# contention and flaky "could not be restarted" timeouts.
#
# The probe itself costs a whole extra interpreter start-up, which is paid on
# every one of those reboots, so its result is cached in a stamp file: the
# dependency check runs once per host and every later boot goes straight to
# `exec`, roughly halving per-test boot latency.
STAMP="${TMPDIR:-/tmp}/.prd_bench_ale_reporting_deps_ok"
if [ ! -e "$STAMP" ]; then
  if ! python3 -c "import flask" >/dev/null 2>&1; then
    python3 -m pip install -q -r requirements.txt
  fi
  : > "$STAMP" 2>/dev/null || true
fi
exec python3 app.py
