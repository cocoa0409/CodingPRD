#!/bin/bash
# Kill leftover runner/pytest/flask processes from prior sweeps of THIS task only.
pkill -f 'task_1133_literary_agency_submission_deal_tracking' 2>/dev/null || true
sleep 1
pkill -9 -f 'task_1133_literary_agency_submission_deal_tracking' 2>/dev/null || true
exit 0
