#!/usr/bin/env bash
# 8-round stability sweep run as 2 waves of 4 to avoid single-task host self-saturation.
# No inline pkill (would self-match and exit 144). Runner claims its own free port per round.
set -u
TASK=/home/ubuntu/github/CodingPRD/tasks/task_1079_ev_fleet_charging_depot
IMPL=$TASK/workspace/implementation
rm -f $IMPL/results.*.json

run_round() {
  local i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       $TASK/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   $IMPL/results.${i}.json
}

# Wave 1: rounds 1-4
for i in 1 2 3 4; do run_round $i & done
wait
# Wave 2: rounds 5-8
for i in 5 6 7 8; do run_round $i & done
wait

echo "=== sweep complete ==="
for i in 1 2 3 4 5 6 7 8; do
  if [ -f $IMPL/results.${i}.json ]; then
    python3 -c "import json;d=json.load(open('$IMPL/results.${i}.json'));print('round $i: passed=%s total=%s'%(d.get('passed'),d.get('total')))" 2>/dev/null || echo "round $i: UNPARSEABLE"
  else
    echo "round $i: MISSING"
  fi
done
