#!/usr/bin/env bash
# 8-round stability sweep, run as 2 waves of 4 to avoid host self-saturation.
# NOTE: no inline pkill anywhere (a `pkill -f <task path>` would match this script itself).
set -u
TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_1055_rebate_incentive_program
IMPL="$TASK_DIR/workspace/implementation"

rm -f "$IMPL"/results.*.json

run_round() {
  local i="$1"
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TASK_DIR/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" \
    > "$IMPL/round.${i}.log" 2>&1
}

for wave in "1 2 3 4" "5 6 7 8"; do
  for i in $wave; do
    run_round "$i" &
  done
  wait
done

echo "=== sweep complete ==="
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "$IMPL/results.${i}.json" ]; then
    python3 - "$IMPL/results.${i}.json" "$i" <<'PY'
import json, sys
p, i = sys.argv[1], sys.argv[2]
d = json.load(open(p))
print(f"round {i}: passed={d.get('passed')} total={d.get('total')}")
PY
  else
    echo "round $i: MISSING results file"
  fi
done
