#!/bin/bash
TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_1005_maternity_nursing_apparel
IMPL=$TASK_DIR/workspace/implementation
rm -f $IMPL/results.*.json
run_round () {
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       $TASK_DIR/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   $IMPL/results.${1}.json
}
for i in 1 2 3 4; do run_round $i & done
wait
for i in 5 6 7 8; do run_round $i & done
wait
echo "SWEEP DONE"
for i in 1 2 3 4 5 6 7 8; do
  python3 -c "import json;d=json.load(open('$IMPL/results.$i.json'));print('round $i:',d.get('passed'),'/',d.get('total'),'failed:',[t['name'] for t in d.get('tests',[]) if t.get('outcome')!='passed'][:40])" 2>/dev/null || echo "round $i: NO/BAD results.json"
done
