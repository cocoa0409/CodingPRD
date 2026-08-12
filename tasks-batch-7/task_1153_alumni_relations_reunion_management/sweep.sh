#!/usr/bin/env bash
# Step 7 parallel 8-round stability sweep for task_1153_alumni_relations_reunion_management.
# Launches all 8 prd-bench-local-run rounds concurrently, joins with wait, then blocks
# until all 8 results files exist. Run from anywhere; paths are absolute.
set -u
TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_1153_alumni_relations_reunion_management
IMPL="$TASK_DIR/workspace/implementation"

rm -f "$IMPL"/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TASK_DIR/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" \
    > "$IMPL/sweep_round_${i}.log" 2>&1 &
done
wait

# Safety poll: wait until all 8 results files exist (wait already joined, this guards stragglers)
until [ "$(ls "$IMPL"/results.*.json 2>/dev/null | wc -l)" -ge 8 ]; do sleep 20; done

echo "SWEEP DONE: $(ls "$IMPL"/results.*.json | wc -l) results files"
for i in 1 2 3 4 5 6 7 8; do
  python3 -c "
import json,sys
try:
    d=json.load(open('$IMPL/results.${i}.json'))
    print('round $i:', json.dumps({k:d.get(k) for k in ('passed','failed','total','errors') if k in d}))
except Exception as e:
    print('round $i: UNREADABLE', e)
"
done
