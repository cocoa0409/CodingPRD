#!/usr/bin/env bash
# Step-7 stability sweep for task_1080 — 8 rounds run as 2 waves of 4 to dodge
# single-task self-saturation (spurious boot-timeout ERRORs when 8 per-test-server
# runs overlap on one host). No inline pkill (avoids pkill self-match exit 144).
set -u
IMPL=/home/ubuntu/github/CodingPRD/tasks/task_1080_exotic_car_storage_vault/workspace/implementation
TESTDIR=/home/ubuntu/github/CodingPRD/tasks/task_1080_exotic_car_storage_vault/test_suite

rm -f "$IMPL"/results.*.json

run_round() {
  local i="$1"
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TESTDIR" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json"
}

# Wave 1: rounds 1-4
for i in 1 2 3 4; do run_round "$i" & done
wait
# Wave 2: rounds 5-8
for i in 5 6 7 8; do run_round "$i" & done
wait

echo "SWEEP_DONE"
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "$IMPL/results.${i}.json" ]; then
    python3 - "$IMPL/results.${i}.json" "$i" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
p=d.get("passed"); t=d.get("total")
print(f"round {sys.argv[2]}: passed={p} total={t}")
PY
  else
    echo "round ${i}: MISSING results file"
  fi
done
