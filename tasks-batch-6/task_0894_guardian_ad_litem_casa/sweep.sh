#!/bin/bash
cd /home/ubuntu/github/CodingPRD/tasks/task_0894_guardian_ad_litem_casa
rm -f workspace/implementation/results.*.json
run_round () {
  local i=$1
  prd-bench-local-run \
    --start-command "cd /home/ubuntu/github/CodingPRD/tasks/task_0894_guardian_ad_litem_casa/workspace/implementation && bash start.sh" \
    --test-dir       /home/ubuntu/github/CodingPRD/tasks/task_0894_guardian_ad_litem_casa/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   workspace/implementation/results.${i}.json
}
# Wave 1
for i in 1 2 3 4; do run_round $i & done
wait
# Wave 2
for i in 5 6 7 8; do run_round $i & done
wait
