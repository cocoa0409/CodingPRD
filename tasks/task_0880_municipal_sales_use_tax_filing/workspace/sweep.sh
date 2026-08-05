#!/usr/bin/env bash
# 8-round stability sweep run as 2 waves of 4 to avoid single-task self-saturation
# (single-task 8-way concurrent per-test-server sweeps overload the host and produce
#  spurious boot-timeout ERRORs). No inline pkill (self-match → exit 144).
set -u
TASK=/home/ubuntu/github/CodingPRD/tasks/task_0880_municipal_sales_use_tax_filing
IMPL=$TASK/workspace/implementation
TESTDIR=$TASK/test_suite

rm -f "$IMPL"/results.*.json

run_round() {
  local i="$1"
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TESTDIR" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" \
    >"$IMPL/round.${i}.log" 2>&1
}

# Wave 1: rounds 1-4
for i in 1 2 3 4; do run_round "$i" & done
wait
# Wave 2: rounds 5-8
for i in 5 6 7 8; do run_round "$i" & done
wait

echo "=== SWEEP DONE ==="
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "$IMPL/results.${i}.json" ]; then
    python3 - "$IMPL/results.${i}.json" "$i" <<'PY'
import json,sys
f,i=sys.argv[1],sys.argv[2]
try:
    d=json.load(open(f))
    print(f"round {i}: passed={d.get('passed')} total={d.get('total')} failed={d.get('failed')} errors={d.get('errors')}")
except Exception as e:
    print(f"round {i}: UNREADABLE {e}")
PY
  else
    echo "round ${i}: MISSING results file"
  fi
done
