#!/bin/bash
# Step 7 — 8-round parallel stability sweep for task_1234.
# Launched detached by the orchestrator; writes sweep_1234.done when all 8 rounds finish.
set -u
TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_1234_homeowners_association_architectural
IMPL=$TASK_DIR/workspace/implementation

rm -f "$IMPL"/results.*.json "$TASK_DIR"/sweep_1234.done
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TASK_DIR/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" \
    > "$TASK_DIR/sweep_round_${i}.log" 2>&1 &
done
wait
touch "$TASK_DIR/sweep_1234.done"
