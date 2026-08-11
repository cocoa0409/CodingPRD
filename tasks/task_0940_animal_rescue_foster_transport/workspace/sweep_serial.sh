#!/usr/bin/env bash
# SERIAL variant of sweep.sh: the same 8 rounds, run ONE AT A TIME.
#
# Why this exists: this host is carrying 5-8 concurrent prd-bench-local-run
# processes belonging to co-tenant tasks, so even sweep.sh's 2-waves-of-4 shape
# pushes the box to load ~10 and produces spurious connection-level failures
# ("could not be restarted", RemoteDisconnected) that masquerade as test
# failures.  Running serially adds exactly ONE runner to the host instead of
# four; it is strictly gentler than sweep.sh and preserves every safety
# property of it:
#   * never 8-way concurrent (never even 2-way);
#   * no inline `pkill -f '<task path>'` (which self-matches -> exit 144);
#   * the --start-command keeps the verbatim "cd <impl> && bash start.sh" prefix;
#   * results land in the same results.N.json paths sweep.sh writes.

set -u

TASK=/home/ubuntu/github/CodingPRD/tasks/task_0940_animal_rescue_foster_transport
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

for i in 1 2 3 4 5 6 7 8; do
  echo "round $i  ($(date -u +%FT%TZ))"
  run_round "$i"
  sleep 2
done

echo "sweep complete ($(date -u +%FT%TZ))"
touch "$IMPL/SWEEP_DONE"
