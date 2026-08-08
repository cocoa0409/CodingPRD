#!/bin/bash
rm -f /home/ubuntu/github/CodingPRD/tasks/task_0892_victim_services_compensation/workspace/implementation/results.*.json
run_round() {
  local i=$1
  prd-bench-local-run \
    --start-command "cd /home/ubuntu/github/CodingPRD/tasks/task_0892_victim_services_compensation/workspace/implementation && bash start.sh" \
    --test-dir       /home/ubuntu/github/CodingPRD/tasks/task_0892_victim_services_compensation/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   /home/ubuntu/github/CodingPRD/tasks/task_0892_victim_services_compensation/workspace/implementation/results.${i}.json
}
reap() {
  for pid in $(ps aux | grep -E 'python.*app.py' | grep -v grep | awk '{print $2}'); do
    kill -9 $pid 2>/dev/null
  done
}
# Wave 1
for i in 1 2 3 4; do run_round $i & done
wait
reap
sleep 3
# Wave 2
for i in 5 6 7 8; do run_round $i & done
wait
reap
echo "SWEEP DONE"
