#!/usr/bin/env bash
# 8-round stability sweep for task_0912, run as TWO WAVES OF FOUR.
#
# Why two waves and not all 8 at once: this suite is 100 tests under
# --isolation per-test-server, i.e. ~100 server boots per round. Eight
# concurrent rounds = ~800 boots in flight and has historically saturated
# the host badly enough that the kernel SIGTERMs (exit 143) whole rounds,
# producing missing/partial results.*.json that look like test failures.
#
# Why a script file and not an inline for-loop: an inline `pkill -f <task path>`
# matches the orchestrating shell's own command line and kills it (exit 144),
# losing every result. Keeping the sweep in a file keeps the pattern out of the
# caller's cmdline.
#
# Usage: bash workspace/sweep.sh          (from anywhere; paths are absolute)

set -u

TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_0912_glp1_weight_loss_telehealth
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

for wave in "1 2 3 4" "5 6 7 8"; do
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
print(f"{p.split('/')[-1]}: passed={d.get('passed')} total={d.get('total')} failed={d.get('failed')}")
PY
  else
    echo "results.${i}.json: MISSING (round died)"
  fi
done

# Completion marker — the caller blocks on this file rather than on the
# foreground process, because a full 2-wave sweep can exceed a single Bash
# tool-call timeout. Launch with:
#   nohup bash workspace/sweep.sh > workspace/sweep.log 2>&1 &
# then poll for workspace/implementation/SWEEP_DONE.
touch "$IMPL/SWEEP_DONE"
