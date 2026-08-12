#!/bin/bash
rm -f /home/ubuntu/github/CodingPRD/tasks/task_1133_literary_agency_submission_deal_tracking/workspace/implementation/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd /home/ubuntu/github/CodingPRD/tasks/task_1133_literary_agency_submission_deal_tracking/workspace/implementation && bash start.sh" \
    --test-dir       /home/ubuntu/github/CodingPRD/tasks/task_1133_literary_agency_submission_deal_tracking/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   /home/ubuntu/github/CodingPRD/tasks/task_1133_literary_agency_submission_deal_tracking/workspace/implementation/results.${i}.json &
done
wait
# block until all 8 results files exist
until [ "$(ls /home/ubuntu/github/CodingPRD/tasks/task_1133_literary_agency_submission_deal_tracking/workspace/implementation/results.*.json 2>/dev/null | wc -l)" -ge 8 ]; do sleep 20; done
