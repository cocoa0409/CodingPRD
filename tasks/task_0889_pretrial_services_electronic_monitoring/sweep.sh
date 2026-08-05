#!/usr/bin/env bash
# Durable 8-round stability sweep, run as 2 waves of 4 (host-saturation safe).
# Leaves results.1.json .. results.8.json on disk. No inline pkill (avoids exit-144 self-kill).
set -u
TASK=/home/ubuntu/github/CodingPRD/tasks/task_0889_pretrial_services_electronic_monitoring
IMPL=$TASK/workspace/implementation
TESTS=$TASK/test_suite

rm -f "$IMPL"/results.*.json

run_round() {
  i=$1
  prd-bench-local-run \
    --start-command "cd $IMPL && bash start.sh" \
    --test-dir       "$TESTS" \
    --isolation      per-test-server \
    --timeout        120 \
    --test-timeout   30 \
    --results-file   "$IMPL/results.${i}.json" \
    > "$IMPL/sweep.${i}.log" 2>&1
}

echo "=== Wave 1: rounds 1-4 ==="
for i in 1 2 3 4; do run_round "$i" & done
wait
echo "=== Wave 2: rounds 5-8 ==="
for i in 5 6 7 8; do run_round "$i" & done
wait
echo "=== sweep complete ==="
