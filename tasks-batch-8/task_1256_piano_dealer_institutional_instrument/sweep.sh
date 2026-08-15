#!/bin/bash
# Step 7 — 8-round parallel stability sweep for task_1256.
# Launches all 8 rounds concurrently, joins with wait, then blocks until all 8 results files exist.
set -u
TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_1256_piano_dealer_institutional_instrument
IMPL="$TASK_DIR/workspace/implementation"

rm -f "$IMPL"/results.*.json
for i in 1 2 3 4 5 6 7 8; do
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TASK_DIR/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" > "$TASK_DIR/sweep_round_${i}.log" 2>&1 &
done
wait

# Block until all 8 results files are on disk (rounds always finish after wait; this is a belt-and-braces poll).
until [ "$(ls "$IMPL"/results.*.json 2>/dev/null | wc -l)" -ge 8 ]; do sleep 20; done

echo "SWEEP_COMPLETE"
for i in 1 2 3 4 5 6 7 8; do
  python3 -c "
import json
d = json.load(open('$IMPL/results.${i}.json'))
s = d.get('summary', d)
print('round $i:', 'passed=%s total=%s failed=%s' % (s.get('passed'), s.get('total'), s.get('failed')))
" 2>/dev/null || echo "round $i: results file unreadable"
done
