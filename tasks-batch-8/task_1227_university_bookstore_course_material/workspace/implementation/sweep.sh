#!/usr/bin/env bash
set -uo pipefail
IMPL=/home/ubuntu/github/CodingPRD/tasks/task_1227_university_bookstore_course_material/workspace/implementation
rm -f "$IMPL"/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd /home/ubuntu/github/CodingPRD/tasks/task_1227_university_bookstore_course_material/workspace/implementation && bash start.sh" \
    --test-dir       /home/ubuntu/github/CodingPRD/tasks/task_1227_university_bookstore_course_material/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" &
done
wait
echo "SWEEP_DONE"
ls -la "$IMPL"/results.*.json 2>/dev/null
