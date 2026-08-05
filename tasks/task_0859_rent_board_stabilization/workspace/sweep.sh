#!/usr/bin/env bash
# sweep.sh — 2 waves of 4 rounds = 8 rounds total, no inline pkill in the caller shell
set -u
TD=/home/ubuntu/github/CodingPRD/tasks/task_0859_rent_board_stabilization
rm -f "$TD"/workspace/implementation/results.*.json
run_round () {
  local i=$1
  prd-bench-local-run \
    --start-command "cd $TD/workspace/implementation && bash start.sh" \
    --test-dir       "$TD/test_suite" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$TD/workspace/implementation/results.${i}.json"
}
for i in 1 2 3 4; do run_round "$i" & done
wait
# reap orphan Flask servers between waves
pkill -f "$TD/workspace/implementation" 2>/dev/null || true
sleep 2
for i in 5 6 7 8; do run_round "$i" & done
wait
pkill -f "$TD/workspace/implementation" 2>/dev/null || true
echo "SWEEP DONE"
