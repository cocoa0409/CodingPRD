#!/usr/bin/env bash
# 8-round sweep as 2 waves of 4. No inline pkill (self-match exit 144).
set -u
TASK=/home/ubuntu/github/CodingPRD/tasks/task_1041_student_travel_ef
IMPL=$TASK/workspace/implementation

rm -f $IMPL/results.*.json

run_round () {
  local i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       $TASK/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   $IMPL/results.${i}.json \
    > $IMPL/round.${i}.log 2>&1
}

# Wave 1: rounds 1-4
for i in 1 2 3 4; do run_round $i & done
wait
# Wave 2: rounds 5-8
for i in 5 6 7 8; do run_round $i & done
wait

echo "=== SWEEP DONE ==="
for i in 1 2 3 4 5 6 7 8; do
  if [ -f $IMPL/results.${i}.json ]; then
    python3 -c "import json;d=json.load(open('$IMPL/results.${i}.json'));print('round $i: passed=%s total=%s'%(d.get('passed'),d.get('total')))"
  else
    echo "round $i: NO RESULTS FILE"
  fi
done
