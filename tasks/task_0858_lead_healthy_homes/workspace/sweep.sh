#!/usr/bin/env bash
T=/home/ubuntu/github/CodingPRD/tasks/task_0858_lead_healthy_homes
rm -f "$T"/workspace/implementation/results.*.json
run_round () {
  prd-bench-local-run \
    --start-command "cd $T/workspace/implementation && bash start.sh" \
    --test-dir       "$T/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$T/workspace/implementation/results.$1.json"
}
# wave 1: rounds 1-4
for i in 1 2 3 4; do run_round $i & done
wait
# wave 2: rounds 5-8
for i in 5 6 7 8; do run_round $i & done
wait
