#!/usr/bin/env bash
# Step-7 stability sweep for task_1095, run as 4 WAVES OF 2 rounds.
# Host has 4 sibling tasks sweeping concurrently on 8 cores; never launch all 8
# rounds at once or per-test-server boots time out (spurious ERRORs).
# Invoke from anywhere: bash sweep.sh
set -uo pipefail
TASK_DIR="/home/ubuntu/github/CodingPRD/tasks/task_1095_per_diem_healthcare_staffing"
IMPL="$TASK_DIR/workspace/implementation"
TESTS="$TASK_DIR/test_suite"

rm -f "$IMPL"/results.*.json

run_round () {
  local i="$1"
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TESTS" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" \
    > "$IMPL/sweep.${i}.log" 2>&1
}

for wave in "1 2" "3 4" "5 6" "7 8"; do
  echo "=== wave: rounds $wave ==="
  for i in $wave; do run_round "$i" & done
  wait
done
echo "=== sweep complete ==="
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "$IMPL/results.${i}.json" ]; then
    python3 - "$IMPL/results.${i}.json" "$i" <<'PY'
import json,sys
f,i=sys.argv[1],sys.argv[2]
d=json.load(open(f))
p=d.get("passed"); t=d.get("total")
print(f"round {i}: passed={p} total={t}")
PY
  else
    echo "round ${i}: MISSING results file"
  fi
done
