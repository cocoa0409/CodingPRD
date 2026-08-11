#!/bin/bash
# 8-round parallel stability sweep for task_1168
IMPL=/home/ubuntu/github/CodingPRD/tasks/task_1168_hedis_quality_measure_abstraction/workspace/implementation
rm -f "$IMPL"/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd /home/ubuntu/github/CodingPRD/tasks/task_1168_hedis_quality_measure_abstraction/workspace/implementation && bash start.sh" \
    --test-dir       /home/ubuntu/github/CodingPRD/tasks/task_1168_hedis_quality_measure_abstraction/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" &
done
wait
until [ "$(ls "$IMPL"/results.*.json 2>/dev/null | wc -l)" -ge 8 ]; do sleep 20; done
echo "SWEEP DONE"
for i in 1 2 3 4 5 6 7 8; do
  python3 -c "
import json
with open('$IMPL/results.$i.json') as f:
    r = json.load(f)
print('round $i: passed={} total={}'.format(r.get('passed'), r.get('total')))
"
done
