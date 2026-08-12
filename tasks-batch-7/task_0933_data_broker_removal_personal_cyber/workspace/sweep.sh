#!/usr/bin/env bash
# 8-round stability sweep for task_0933, run as 2 waves of 4 concurrent rounds.
# Host is 8-core; 125 tests x per-test-server = ~125 boots per round. Running all 8
# rounds at once has previously saturated the host and mass-SIGTERMed the runs,
# so the sweep is split into waves.
#
# Usage:  nohup bash sweep.sh > sweep.out 2>&1 &
# then poll for the marker file $IMPL/SWEEP_DONE (the whole sweep can exceed a
# single tool-call timeout, so do not run this in the foreground).
#
# Do NOT add an inline `pkill -f '<task path>'` here: the pattern matches this
# script's own command line and kills the shell (exit 144) before results land.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_0933_data_broker_removal_personal_cyber
IMPL=$TASK/workspace/implementation

rm -f "$IMPL"/results.*.json "$IMPL"/SWEEP_DONE "$TASK"/workspace/round.*.log

run_round () {
  local i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TASK/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" \
    > "$TASK/workspace/round.${i}.log" 2>&1
}

echo "=== wave 1: rounds 1-4 @ $(date -u +%FT%TZ) ==="
for i in 1 2 3 4; do run_round "$i" & done
wait

echo "=== wave 2: rounds 5-8 @ $(date -u +%FT%TZ) ==="
for i in 5 6 7 8; do run_round "$i" & done
wait

echo "=== sweep complete @ $(date -u +%FT%TZ) ==="
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "$IMPL/results.${i}.json" ]; then
    python3 - "$IMPL/results.${i}.json" <<'PY'
import json,sys
p=sys.argv[1]
try:
    d=json.load(open(p))
    rows=d.get('tests') or d.get('results') or []
    print(f"{p.split('/')[-1]}: passed={d.get('passed')} failed={d.get('failed')} total={d.get('total')} rows={len(rows)}")
except Exception as e:
    print(f"{p.split('/')[-1]}: UNPARSEABLE {e}")
PY
  else
    echo "results.${i}.json: MISSING"
  fi
done

touch "$IMPL/SWEEP_DONE"
