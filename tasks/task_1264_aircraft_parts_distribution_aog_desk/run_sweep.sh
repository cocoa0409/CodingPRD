#!/usr/bin/env bash
set -uo pipefail

IMPL=/home/ubuntu/github/CodingPRD/tasks/task_1264_aircraft_parts_distribution_aog_desk/workspace/implementation

rm -f "${IMPL}"/results.*.json

for i in 1 2 3 4 5 6 7 8; do
  BOOT_LOG=/tmp/aog_boot_round${i}.log prd-bench-local-run \
    --start-command "cd /home/ubuntu/github/CodingPRD/tasks/task_1264_aircraft_parts_distribution_aog_desk/workspace/implementation && bash start.sh" \
    --test-dir       /home/ubuntu/github/CodingPRD/tasks/task_1264_aircraft_parts_distribution_aog_desk/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "${IMPL}/results.${i}.json" &
done
wait

until [ "$(ls "${IMPL}"/results.*.json 2>/dev/null | wc -l)" -ge 8 ]; do sleep 20; done

echo "=== SWEEP COMPLETE ==="
for i in 1 2 3 4 5 6 7 8; do
  f="${IMPL}/results.${i}.json"
  if [ -f "$f" ]; then
    python3 -c "
import json
d = json.load(open('$f'))
passed = d.get('passed', 0)
total = d.get('total', 0)
failed = d.get('failed', 0)
print('round $i: passed=%s total=%s failed=%s' % (passed, total, failed))
fails = [t for t in d.get('tests', []) if t.get('status') != 'passed']
for t in fails:
    print('  FAIL:', t.get('nodeid', t.get('name')))
"
  else
    echo "round $i: MISSING results file"
  fi
done
