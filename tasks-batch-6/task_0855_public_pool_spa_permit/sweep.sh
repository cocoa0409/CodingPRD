#!/usr/bin/env bash
# 8-round stability sweep for task_0855_public_pool_spa_permit, run as 2 WAVES OF 4.
# Two waves (not 8-at-once) avoids single-task self-saturation, which shows up as
# spurious boot-timeout ERRORs that look like real failures.
# NOTE: no inline `pkill -f '<task path>'` — such a pattern matches this script's own
# argv and kills the shell (exit 144, no results.json).
set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_0855_public_pool_spa_permit
IMPL="$TASK_DIR/workspace/implementation"

cd /home/ubuntu/github/CodingPRD || exit 1   # never cd into IMPL (orphan-reap self-kill)

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

echo "=== sweep done ==="
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "$IMPL/results.${i}.json" ]; then
    python3 - "$IMPL/results.${i}.json" <<'PY'
import json,sys
p=sys.argv[1]
try:
    d=json.load(open(p))
except Exception as e:
    print(p,"UNREADABLE",e); sys.exit()
print(p.split('/')[-1], "passed=%s total=%s" % (d.get("passed"), d.get("total")))
PY
  else
    echo "results.${i}.json MISSING"
  fi
done
