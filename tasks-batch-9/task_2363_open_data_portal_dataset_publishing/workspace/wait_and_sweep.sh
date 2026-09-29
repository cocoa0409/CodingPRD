#!/bin/bash
# Wait for host load to fall below a threshold, then run the 8-round sweep.
TD=/home/ubuntu/github/CodingPRD/tasks/task_2363_open_data_portal_dataset_publishing
THRESH=${1:-100}
MAXWAIT=${2:-3600}
rm -f "$TD/workspace/SWEEP_DONE"
start=$(date +%s)
while :; do
  l1=$(cut -d' ' -f1 /proc/loadavg | cut -d. -f1)
  now=$(date +%s)
  if [ "$l1" -lt "$THRESH" ] || [ $((now-start)) -ge "$MAXWAIT" ]; then
    echo "$(date -u) launching sweep at load1=$l1 waited=$((now-start))s" >> "$TD/workspace/sweeplogs/driver.log"
    break
  fi
  sleep 30
done
bash "$TD/workspace/sweep.sh"
