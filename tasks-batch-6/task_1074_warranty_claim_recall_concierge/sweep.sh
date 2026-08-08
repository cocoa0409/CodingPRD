#!/usr/bin/env bash
# 8-round stability sweep run as 2 waves of 4 (dodges single-task self-saturation
# that produces spurious boot-timeout ERRORs when 8 per-test-server rounds overlap).
# No inline pkill (self-match would exit 144); the runner owns port allocation via flock.
set -u
TASK=/home/ubuntu/github/CodingPRD/tasks/task_1074_warranty_claim_recall_concierge
IMPL=$TASK/workspace/implementation
TESTS=$TASK/test_suite

rm -f "$IMPL"/results.*.json

run_round () {
  local i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir      "$TESTS" \
    --isolation     per-test-server \
    --timeout       120 \
    --test-timeout  30 \
    --results-file  "$IMPL/results.${i}.json"
}

# Wave 1: rounds 1-4
for i in 1 2 3 4; do run_round "$i" & done
wait
# Wave 2: rounds 5-8
for i in 5 6 7 8; do run_round "$i" & done
wait

echo "=== sweep complete ==="
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "$IMPL/results.${i}.json" ]; then
    python3 - "$IMPL/results.${i}.json" "$i" <<'PY'
import json,sys
f,i=sys.argv[1],sys.argv[2]
d=json.load(open(f))
p=d.get('passed'); t=d.get('total')
tests=d.get('tests',[])
skips=[x.get('name') for x in tests if str(x.get('outcome','')).lower() in ('skipped','xfail','xfailed')]
print(f"round {i}: passed={p} total={t} skipped/xfail={len(skips)}")
PY
  else
    echo "round ${i}: NO RESULTS FILE"
  fi
done
