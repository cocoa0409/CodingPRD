#!/usr/bin/env bash
# Sweep script — run from file, never inline (avoids pkill self-match exit 144).
set -u
TASK=/home/ubuntu/github/CodingPRD/tasks/task_1014_candle_soap_bath_dtc
IMPL=$TASK/workspace/implementation

# Reap any orphan Flask servers from prior runs (safe: not self-matching a Bash tool shell).
pkill -f 'implementation/app.py' 2>/dev/null || true
sleep 1

rm -f $IMPL/results.*.json

WAVE="$1"  # "8" for all-8-at-once, or "4" for 2 waves of 4

run_round () {
  local i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       $TASK/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   $IMPL/results.${i}.json
}

if [ "$WAVE" = "4" ]; then
  for i in 1 2 3 4; do run_round $i & done
  wait
  pkill -f 'implementation/app.py' 2>/dev/null || true
  sleep 2
  for i in 5 6 7 8; do run_round $i & done
  wait
else
  for i in 1 2 3 4 5 6 7 8; do run_round $i & done
  wait
fi

pkill -f 'implementation/app.py' 2>/dev/null || true
echo "SWEEP_DONE"
