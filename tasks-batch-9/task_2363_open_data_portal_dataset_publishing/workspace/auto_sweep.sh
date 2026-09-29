#!/bin/bash
TD=/home/ubuntu/github/CodingPRD/tasks/task_2363_open_data_portal_dataset_publishing
THRESH=${1:-110}
ATTEMPTS=${2:-12}
DL=$TD/workspace/sweeplogs/driver.log
mkdir -p $TD/workspace/sweeplogs
rm -f $TD/workspace/SWEEP_CLEAN $TD/workspace/SWEEP_REAL
for a in $(seq 1 $ATTEMPTS); do
  waited=0
  while :; do
    l1=$(cut -d' ' -f1 /proc/loadavg | cut -d. -f1)
    [ "$l1" -lt "$THRESH" ] && break
    [ "$waited" -ge 7200 ] && break
    sleep 30; waited=$((waited+30))
  done
  echo "$(date -u) attempt $a launching at load1=$(cut -d' ' -f1 /proc/loadavg) waited=${waited}s" >> $DL
  bash $TD/workspace/sweep.sh
  echo "$(date -u) attempt $a finished" >> $DL
  python3 $TD/workspace/classify.py > $TD/workspace/sweeplogs/verdict_${a}.txt 2>&1
  rc=$?
  cp $TD/workspace/sweeplogs/verdict_${a}.txt $TD/workspace/sweeplogs/verdict_latest.txt
  echo "$(date -u) attempt $a verdict rc=$rc" >> $DL
  if [ "$rc" -eq 0 ]; then touch $TD/workspace/SWEEP_CLEAN; break; fi
  if [ "$rc" -eq 1 ]; then touch $TD/workspace/SWEEP_REAL; break; fi
  sleep 60
done
touch $TD/workspace/AUTO_DONE
