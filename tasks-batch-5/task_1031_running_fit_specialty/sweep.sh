#!/bin/bash
cd /home/ubuntu/github/CodingPRD/tasks/task_1031_running_fit_specialty
rm -f workspace/implementation/results.*.json
run_round() {
  prd-bench-local-run \
    --start-command "cd /home/ubuntu/github/CodingPRD/tasks/task_1031_running_fit_specialty/workspace/implementation && bash start.sh" \
    --test-dir       /home/ubuntu/github/CodingPRD/tasks/task_1031_running_fit_specialty/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   workspace/implementation/results.$1.json
}
for i in 1 2 3 4; do run_round $i & done
wait
for i in 5 6 7 8; do run_round $i & done
wait
echo "SWEEP DONE"
