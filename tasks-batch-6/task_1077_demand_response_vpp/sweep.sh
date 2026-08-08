#!/usr/bin/env bash
# 8-round stability sweep run as 2 waves of 4 to avoid single-task self-saturation.
# No inline pkill (avoids self-match exit 144). Each round claims its own free port
# via the runner's file-locked registry. Runs all 8 to completion, no early exit.
set -u
TASK=/home/ubuntu/github/CodingPRD/tasks/task_1077_demand_response_vpp
IMPL="$TASK/workspace/implementation"
TESTS="$TASK/test_suite"

rm -f "$IMPL"/results.*.json

run_round() {
  local i="$1"
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TESTS" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" \
    >"$IMPL/sweep.${i}.log" 2>&1
}

# Wave 1: rounds 1-4
for i in 1 2 3 4; do run_round "$i" & done
wait
# Wave 2: rounds 5-8
for i in 5 6 7 8; do run_round "$i" & done
wait

echo "=== sweep complete ==="
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "$IMPL/results.${i}.json" ]; then
    python3 -c "import json;d=json.load(open('$IMPL/results.${i}.json'));print('round $i: passed=%s total=%s'%(d.get('passed'),d.get('total')))" 2>/dev/null \
      || echo "round $i: UNPARSEABLE"
  else
    echo "round $i: NO RESULTS FILE"
  fi
done
