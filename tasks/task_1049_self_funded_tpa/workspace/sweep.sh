#!/bin/bash
cd /home/ubuntu/github/CodingPRD/tasks/task_1049_self_funded_tpa
rm -f workspace/implementation/results.*.json
run_wave() {
  for i in "$@"; do
    prd-bench-local-run \
      --start-command "cd /home/ubuntu/github/CodingPRD/tasks/task_1049_self_funded_tpa/workspace/implementation && bash start.sh" \
      --test-dir       /home/ubuntu/github/CodingPRD/tasks/task_1049_self_funded_tpa/test_suite \
      --isolation      per-test-server \
      --timeout        120 \
      --test-timeout   30 \
      --results-file   /home/ubuntu/github/CodingPRD/tasks/task_1049_self_funded_tpa/workspace/implementation/results.${i}.json &
  done
  wait
}
run_wave 1 2 3 4
run_wave 5 6 7 8
echo "SWEEP_DONE"
