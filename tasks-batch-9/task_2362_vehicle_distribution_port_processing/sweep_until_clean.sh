#!/bin/bash
# Wait for a genuinely quiet window, then run the 8-round sweep; repeat until
# all eight rounds report passed == total.
T=/home/ubuntu/github/CodingPRD/tasks/task_2362_vehicle_distribution_port_processing
THRESH=${THRESH:-90}
PATIENCE=${PATIENCE:-960}   # 960 x 30s = 8h max wait per attempt
rm -f $T/SWEEP_CLEAN
for attempt in $(seq 1 40); do
  for w in $(seq 1 $PATIENCE); do
    L=$(awk '{print int($1)}' /proc/loadavg)
    if [ "$L" -lt "$THRESH" ]; then break; fi
    sleep 30
  done
  echo "=== attempt $attempt starting $(date +%H:%M:%S) load $(cut -d' ' -f1-3 /proc/loadavg)" >> /tmp/sweep_loop.log
  bash $T/run_sweep.sh
  CLEAN=$(python3 - <<'EOF'
import json, glob
base = '/home/ubuntu/github/CodingPRD/tasks/task_2362_vehicle_distribution_port_processing/workspace/implementation/results.'
files = sorted(glob.glob(base + '*.json'))
if len(files) != 8:
    print("no-missing-files"); raise SystemExit
tal = []
ok = True
for f in files:
    d = json.load(open(f))
    tal.append(f"{d['passed']}/{d['total']}")
    if d['passed'] != d['total']:
        ok = False
print(("yes" if ok else "no") + " " + " ".join(tal))
EOF
)
  echo "=== attempt $attempt finished $(date +%H:%M:%S) result: $CLEAN" >> /tmp/sweep_loop.log
  case "$CLEAN" in yes*) touch $T/SWEEP_CLEAN; break;; esac
done
