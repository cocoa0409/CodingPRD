#!/bin/bash
T=/home/ubuntu/github/CodingPRD/tasks/task_0879_transient_occupancy_hotel_tax
rm -f $T/workspace/implementation/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $T/workspace/implementation && bash start.sh" \
    --test-dir       $T/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   $T/workspace/implementation/results.${i}.json &
done
wait
echo "=== SWEEP DONE ==="
for i in 1 2 3 4 5 6 7 8; do
  python3 -c "import json;d=json.load(open('$T/workspace/implementation/results.$i.json'));print('round $i:',d.get('passed'),'/',d.get('total'),'failed:',len(d.get('failed_tests',d.get('failures',[]))) if isinstance(d.get('failed_tests',d.get('failures',[])),list) else d.get('failed'))" 2>&1
done
