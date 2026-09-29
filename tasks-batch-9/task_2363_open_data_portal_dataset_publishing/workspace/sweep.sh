#!/bin/bash
# 8-round parallel stability sweep for task_2363.
TD=/home/ubuntu/github/CodingPRD/tasks/task_2363_open_data_portal_dataset_publishing
LOGS=$TD/workspace/sweeplogs
mkdir -p "$LOGS"
rm -f "$TD"/workspace/implementation/results.*.json "$LOGS"/round_*.log "$TD"/workspace/SWEEP_DONE
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $TD/workspace/implementation && bash start.sh" \
    --test-dir       "$TD/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$TD/workspace/implementation/results.${i}.json" > "$LOGS/round_${i}.log" 2>&1 &
done
wait
touch "$TD/workspace/SWEEP_DONE"
