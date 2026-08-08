#!/bin/bash
# 8-round stability sweep as 4 waves of 2 (host-saturation mitigation)
TASK=/home/ubuntu/github/CodingPRD/tasks/task_1092_co_living_by_the_room_rental
IMPL=$TASK/workspace/implementation
rm -f $IMPL/results.*.json
run_round () {
  local i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       $TASK/test_suite \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   $IMPL/results.${i}.json
}
for wave in "1 2" "3 4" "5 6" "7 8"; do
  set -- $wave
  run_round $1 &
  run_round $2 &
  wait
done
# reap only our own orphan flask servers (match this task's impl path in cmdline)
for pid in $(pgrep -f "$IMPL"); do kill $pid 2>/dev/null; done
echo "SWEEP DONE"
