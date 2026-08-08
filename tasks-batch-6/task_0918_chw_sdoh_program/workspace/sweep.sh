#!/usr/bin/env bash
# 8-round stability sweep for task_0918_chw_sdoh_program, run as 2 waves of 4.
# Waves (not a single 8-way burst) avoid host saturation / mass SIGTERM.
# Ends by touching $IMPL/SWEEP_DONE so a caller can foreground-poll for completion.
#
# Usage:  nohup bash workspace/sweep.sh > workspace/sweep.out 2>&1 &
#         then poll for  workspace/implementation/SWEEP_DONE

TASK=/home/ubuntu/github/CodingPRD/tasks/task_0918_chw_sdoh_program
IMPL=$TASK/workspace/implementation

rm -f "$IMPL"/results.*.json "$IMPL"/SWEEP_DONE "$TASK"/workspace/round.*.log

run_round () {
  local i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TASK/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" \
    > "$TASK/workspace/round.${i}.log" 2>&1
}

# 4 waves of 2: a co-tenant pipeline (task_0917) is sweeping on the same host.
# 4-wide here + 4-wide there = the 8-way saturation that has previously caused
# mass SIGTERM (exit 143) and lost results.json files.
for wave in "1 2" "3 4" "5 6" "7 8"; do
  echo "=== wave: rounds $wave ==="
  for i in $wave; do run_round $i & done
  wait
  echo "=== wave $wave done ==="
done

for i in 1 2 3 4 5 6 7 8; do
  if [ -f "$IMPL/results.${i}.json" ]; then
    python3 - "$IMPL/results.${i}.json" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
p=d.get("passed"); t=d.get("total")
print(f"{sys.argv[1].split('/')[-1]}: passed={p} total={t}")
PY
  else
    echo "results.${i}.json MISSING"
  fi
done

touch "$IMPL/SWEEP_DONE"
echo "=== SWEEP COMPLETE ==="
