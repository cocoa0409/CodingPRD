#!/usr/bin/env bash
cd /home/ubuntu/github/CodingPRD/tasks/task_0904_smoking_cessation_quitline
rm -f workspace/implementation/results.*.json
run_wave() {
  for i in "$@"; do
    prd-bench-local-run \
      --start-command "cd /home/ubuntu/github/CodingPRD/tasks/task_0904_smoking_cessation_quitline/workspace/implementation && bash start.sh" \
      --test-dir       /home/ubuntu/github/CodingPRD/tasks/task_0904_smoking_cessation_quitline/test_suite \
      --isolation      per-test-server \
      --timeout        120 \
      --test-timeout   30 \
      --results-file   workspace/implementation/results.${i}.json &
  done
  wait
}
run_wave 1 2 3 4
run_wave 5 6 7 8
