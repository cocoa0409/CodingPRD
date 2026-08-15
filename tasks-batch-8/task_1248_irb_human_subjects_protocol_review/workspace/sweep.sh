#!/usr/bin/env bash
set -u
IMPL=/home/ubuntu/github/CodingPRD/tasks/task_1248_irb_human_subjects_protocol_review/workspace/implementation
rm -f "$IMPL"/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd /home/ubuntu/github/CodingPRD/tasks/task_1248_irb_human_subjects_protocol_review/workspace/implementation && bash start.sh" \
    --test-dir       /home/ubuntu/github/CodingPRD/tasks/task_1248_irb_human_subjects_protocol_review/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" > "$IMPL/sweep_round_${i}.log" 2>&1 &
done
wait
until [ "$(ls "$IMPL"/results.*.json 2>/dev/null | wc -l)" -ge 8 ]; do sleep 20; done
echo "=== ALL ROUNDS DONE ==="
ls -la "$IMPL"/results.*.json
