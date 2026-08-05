#!/bin/bash
BASE=/home/ubuntu/github/CodingPRD/tasks/task_0861_precinct_redistricting
rm -f "$BASE"/workspace/implementation/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $BASE/workspace/implementation && bash start.sh" \
    --test-dir       "$BASE/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$BASE/workspace/implementation/results.${i}.json" &
done
wait
echo "SWEEP DONE"
