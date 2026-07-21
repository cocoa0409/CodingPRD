#!/bin/bash
# 8-round stability sweep, run as 2 waves of 4 to avoid single-task host self-saturation.
T=/home/ubuntu/github/CodingPRD/tasks/task_1056_developer_marketplace_payouts
rm -f $T/workspace/implementation/results.*.json
for wave in "1 2 3 4" "5 6 7 8"; do
  for i in $wave; do
    prd-bench-local-run \
      --start-command "cd $T/workspace/implementation && bash start.sh" \
      --test-dir       $T/test_suite \
      --isolation      per-test-server \
      --timeout        120 \
      --test-timeout   30 \
      --results-file   $T/workspace/implementation/results.${i}.json &
  done
  wait
done
python3 - <<'PY'
import json,glob
for f in sorted(glob.glob('/home/ubuntu/github/CodingPRD/tasks/task_1056_developer_marketplace_payouts/workspace/implementation/results.*.json')):
    d=json.load(open(f))
    print(f.split('/')[-1], d.get('passed'), '/', d.get('total'))
PY
