#!/usr/bin/env bash
# 8-round stability sweep for task_0914, run as FOUR WAVES OF TWO.
#
# Why small waves: this suite is 87 tests under --isolation per-test-server,
# i.e. ~87 server boots per round. Eight concurrent rounds = ~700 boots in
# flight and has historically saturated this 8-core host badly enough that the
# kernel SIGTERMs (exit 143) whole rounds, producing missing/partial
# results.*.json that look like test failures. A SECOND prd-bench pipeline
# (task_0913) is running on this host concurrently, so the per-task budget is
# halved again: 2 concurrent rounds, four waves.
#
# Why a script file and not an inline for-loop: an inline `pkill -f <task path>`
# matches the orchestrating shell's own command line and kills it (exit 144),
# losing every result. Keeping the sweep in a file keeps the pattern out of the
# caller's cmdline. Do NOT add pkill to this script.
#
# Usage: nohup bash workspace/sweep.sh > workspace/sweep.log 2>&1 &
#        then poll for workspace/implementation/SWEEP_DONE

set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_0914_school_based_health_center
IMPL="$TASK_DIR/workspace/implementation"

rm -f "$IMPL"/results.*.json "$IMPL"/round.*.log "$IMPL"/SWEEP_DONE

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
  echo "round ${i} exited $?"
}

for wave in "1 2" "3 4" "5 6" "7 8"; do
  echo "=== wave: $wave ==="
  for i in $wave; do
    run_round "$i" &
  done
  wait
  sleep 3
done

echo "=== sweep complete ==="
for i in 1 2 3 4 5 6 7 8; do
  if [ -f "$IMPL/results.${i}.json" ]; then
    python3 - "$IMPL/results.${i}.json" <<'PY'
import json, sys
p = sys.argv[1]
try:
    d = json.load(open(p))
except Exception as e:
    print(f"{p}: UNPARSEABLE ({e})"); sys.exit(0)
rows = d.get("tests") or d.get("results") or []
print(f"{p.split('/')[-1]}: passed={d.get('passed')} total={d.get('total')} "
      f"failed={d.get('failed')} rows={len(rows)}")
PY
  else
    echo "results.${i}.json: MISSING (round died)"
  fi
done

# Completion marker — the caller blocks on this file rather than on the
# foreground process, because a full 4-wave sweep can exceed a single Bash
# tool-call timeout.
touch "$IMPL/SWEEP_DONE"
