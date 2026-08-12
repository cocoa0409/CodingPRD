#!/usr/bin/env bash
# Step 7 parallel 8-round stability sweep for task_1116_hazmat_transportation_compliance
set -u
TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_1116_hazmat_transportation_compliance
IMPL=$TASK_DIR/workspace/implementation

rm -f "$IMPL"/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd /home/ubuntu/github/CodingPRD/tasks/task_1116_hazmat_transportation_compliance/workspace/implementation && bash start.sh" \
    --test-dir       "$TASK_DIR/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" > "$IMPL/sweep_round_${i}.log" 2>&1 &
done
wait
echo "SWEEP_COMPLETE $(date -u +%Y-%m-%dT%H:%M:%SZ)"
ls -l "$IMPL"/results.*.json
