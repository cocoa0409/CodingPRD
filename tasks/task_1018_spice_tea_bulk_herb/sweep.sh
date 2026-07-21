#!/usr/bin/env bash
D=/home/ubuntu/github/CodingPRD/tasks/task_1018_spice_tea_bulk_herb
rm -f "$D"/workspace/implementation/results.*.json
pkill -f 'workspace/implementation/app.py' 2>/dev/null
sleep 1
run(){ prd-bench-local-run --start-command "cd $D/workspace/implementation && bash start.sh" --test-dir "$D/test_suite" --isolation per-test-server --timeout 120 --test-timeout 30 --results-file "$D/workspace/implementation/results.$1.json"; }
for i in 1 2 3 4; do run $i & done; wait
for i in 5 6 7 8; do run $i & done; wait
echo "SWEEP DONE"
