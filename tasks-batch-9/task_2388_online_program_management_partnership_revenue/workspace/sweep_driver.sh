#!/usr/bin/env bash
# Retry driver: repeats the 8-round parallel sweep until every round has passed == total.
# Fully detached (setsid) so the runners are never orphan-killed mid-write.
#
# The host is shared with dozens of peer pipelines running this same harness. At high
# load the harness's own port-cleanup step (`lsof -ti:PORT`, hard 5s timeout) and its
# server restarts fail, producing setup errors and ConnectionResetErrors that are pure
# infrastructure noise. Running a 25-minute sweep at load 700 is wasted work, so this
# driver waits patiently for a genuinely quiet window before each attempt.
TD=/home/ubuntu/github/CodingPRD/tasks/task_2388_online_program_management_partnership_revenue
IMP=$TD/workspace/implementation
STATE=$TD/workspace/driver_state.txt

LOAD_TARGET=100      # preferred load1 before starting a sweep (32-core box)
LOAD_FALLBACK=160    # after the patience budget, accept this
PATIENCE=40          # 40 * 30s = 20min of waiting for the target

for attempt in $(seq 1 40); do
  waited=0
  while [ "$waited" -lt "$PATIENCE" ]; do
    L=$(cut -d' ' -f1 /proc/loadavg | cut -d. -f1)
    [ "$L" -lt "$LOAD_TARGET" ] && break
    sleep 30
    waited=$((waited + 1))
  done
  # If patience ran out, hold out at least for the softer ceiling.
  while :; do
    L=$(cut -d' ' -f1 /proc/loadavg | cut -d. -f1)
    [ "$L" -lt "$LOAD_FALLBACK" ] && break
    sleep 30
  done

  L=$(cut -d' ' -f1 /proc/loadavg | cut -d. -f1)
  echo "attempt $attempt start $(date +%H:%M:%S) load1=$L waited=${waited}x30s" >> "$STATE"

  rm -f "$IMP"/results.*.json
  pids=""
  for i in 1 2 3 4 5 6 7 8; do
    prd-bench-local-run \
      --start-command "cd $IMP && bash start.sh" \
      --test-dir       "$TD/test_suite" \
      --isolation      per-test-server \
      --timeout        120 \
      --test-timeout   30 \
      --results-file   "$IMP/results.${i}.json" > "$TD/workspace/sweeprun_$i.log" 2>&1 &
    pids="$pids $!"
  done
  wait $pids

  verdict=$(python3 - "$IMP" <<'PY'
import json, glob, os, sys
imp = sys.argv[1]
files = sorted(glob.glob(os.path.join(imp, 'results.*.json')))
if len(files) != 8:
    print("INCOMPLETE files=%d" % len(files)); raise SystemExit
rows, clean, realfail = [], True, set()
for f in files:
    d = json.load(open(f))
    rows.append("%d/%d(f=%d,e=%d)" % (d['passed'], d['total'], d['failed'], d['errors']))
    if d['passed'] != d['total']:
        clean = False
    for t in d['tests']:
        if t['status'] == 'failed':
            realfail.add(t['name'])
print(("CLEAN " if clean else "DIRTY ") + " ".join(rows) + " realfail=" + (",".join(sorted(realfail)) or "NONE"))
PY
)
  echo "attempt $attempt end   $(date +%H:%M:%S) load1=$(cut -d' ' -f1 /proc/loadavg) $verdict" >> "$STATE"
  case "$verdict" in
    CLEAN*) echo "ALL_ROUNDS_GREEN" >> "$STATE"; exit 0 ;;
  esac
done
echo "EXHAUSTED_ATTEMPTS" >> "$STATE"
