#!/bin/bash
TASK_DIR=/home/ubuntu/github/CodingPRD/tasks/task_1143_fiscal_sponsorship_administration
until [ "$(ls "$TASK_DIR"/workspace/implementation/results.*.json 2>/dev/null | wc -l)" -ge 8 ]; do
  sleep 20
done
echo "ALL 8 RESULTS PRESENT"
