#!/usr/bin/env bash
# Verify a completed delivery against the local source (read-only).
# Usage:
#   bash verify_delivery.sh <harbor_tasks_dir> <bucket> <licensed|sample> \
#        <dataset> <delivery_YYYY-MM-DD> [region] [upload_log]
set -u
SRC="${1:?usage: verify_delivery.sh <dir> <bucket> <class> <dataset> <YYYY-MM-DD> [region] [log]}"
BUCKET="${2:?}"; CLASS="${3:?}"; DATASET="${4:?}"; DELIV="${5:?}"; REGION="${6:-us-east-2}"; LOG="${7:-}"
[ -d "$SRC" ] || { echo "ERROR: source not found: $SRC" >&2; exit 2; }
PFX="s3://${BUCKET}/${CLASS}/dataset=${DATASET}/delivery=${DELIV}/"

files=$(find "$SRC" -type f | wc -l | tr -d ' ')
dss=$(find "$SRC" -name '.DS_Store' | wc -l | tr -d ' ')
exp=$((files-dss))
tasks=$(find "$SRC" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')

echo "Counting S3 objects under $PFX"
echo "(recursive ls over a large delivery can take minutes)..."
got=$(aws s3 ls "$PFX" --recursive --region "$REGION" | wc -l | tr -d ' ')
prefixes=$(aws s3 ls "$PFX" --region "$REGION" | grep -c 'PRE')
bad=$(aws s3 ls "$PFX" --region "$REGION" | awk '{print $2}' | grep -E '[-A-Z.]' || true)

echo "------------------------------------------------"
echo "objects:       got=$got  expected=$exp  $([ "$got" -eq "$exp" ] && echo OK || echo "MISMATCH(diff=$((got-exp)))")"
echo "task prefixes: got=$prefixes  expected=$tasks  $([ "$prefixes" -eq "$tasks" ] && echo OK || echo MISMATCH)"
if [ -n "$bad" ]; then echo "NON-COMPLIANT PREFIXES (should be none):"; echo "$bad"; else echo "prefixes:      all snake_case OK"; fi
[ -n "$LOG" ] && [ -f "$LOG" ] && echo "log failures:  $(grep -c 'upload failed:' "$LOG")"
echo "------------------------------------------------"
if [ "$got" -eq "$exp" ] && [ "$prefixes" -eq "$tasks" ] && [ -z "$bad" ]; then
  echo "VERIFY: PASS"
else
  echo "VERIFY: FAIL  (re-run upload_delivery.sh — sync will fill the gaps)"; exit 1
fi
