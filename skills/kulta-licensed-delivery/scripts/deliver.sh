#!/bin/bash
# kulta-licensed-delivery: formal (LICENSED) delivery of a finished dataset
# folder to the kulta vendor bucket, then verify.
#
# Hard constraints (enforced below, do not bypass):
#   * Source folder MUST sit directly under the fixed delivery base.
#   * Folder name MUST be  {DATASET_NAME}_{YYYY-MM-DD}  (dataset in [a-z0-9_]).
#   * Destination is derived, never typed by hand:
#       s3://kulta-licensed/licensed/dataset={DATASET_NAME}/delivery={YYYY-MM-DD}/
#
# Usage:
#   bash deliver.sh <folder_name_or_path> [--dry-run] [--no-verify]
# Examples:
#   bash deliver.sh prd_to_repo_2026-06-29
#   bash deliver.sh prd_to_repo_2026-06-29 --dry-run
#
# macOS bash 3.2 compatible (no `declare -A`).
set -u

BASE="${KULTA_BASE:-/Users/uni/Desktop/吉/product_delivery_workspace/delivery}"
BUCKET="kulta-licensed"
CLASS="licensed"
REGION="${KULTA_REGION:-us-east-2}"

die() { echo "ERROR: $*" >&2; exit 2; }

ARG=""; DRYRUN=""; VERIFY=1
for a in "$@"; do
  case "$a" in
    --dry-run|--dryrun) DRYRUN="--dryrun" ;;
    --no-verify)        VERIFY=0 ;;
    -*)                 die "unknown option: $a" ;;
    *)  if [ -z "$ARG" ]; then ARG="$a"; else die "unexpected extra arg: $a"; fi ;;
  esac
done
[ -n "$ARG" ] || die "usage: deliver.sh <folder_name_or_path> [--dry-run] [--no-verify]"

# --- resolve to an absolute, canonical directory ---
case "$ARG" in
  */*) CAND="$ARG" ;;        # looks like a path
  *)   CAND="$BASE/$ARG" ;;  # bare folder name -> under the delivery base
esac
[ -d "$CAND" ] || die "not a directory: $CAND"
DIR="$(cd "$CAND" && pwd -P)"    || die "cannot resolve: $CAND"
BASE_C="$(cd "$BASE" && pwd -P)" || die "delivery base not found: $BASE"

# --- guard 1: must sit DIRECTLY under the delivery base ---
PARENT="$(dirname "$DIR")"
[ "$PARENT" = "$BASE_C" ] || die "refusing: '$DIR' is not directly under the delivery base ($BASE_C). This skill only uploads folders in that directory."

# --- guard 2: name must be {dataset}_{YYYY-MM-DD}, dataset in [a-z0-9_] ---
NAME="$(basename "$DIR")"
if [[ "$NAME" =~ ^([a-z0-9_]+)_([0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9])$ ]]; then
  DATASET="${BASH_REMATCH[1]}"
  DELIV="${BASH_REMATCH[2]}"
else
  die "folder name must be {DATASET_NAME}_{YYYY-MM-DD} with dataset in [a-z0-9_]; got: $NAME"
fi

# --- upload source: the harbor_tasks/ subdir if present, else the folder ---
if [ -d "$DIR/harbor_tasks" ]; then SRC="$DIR/harbor_tasks"; else SRC="$DIR"; fi

DEST="s3://${BUCKET}/${CLASS}/dataset=${DATASET}/delivery=${DELIV}/"

# --- local counts ---
files=$(find "$SRC" -type f ! -name '.DS_Store' | wc -l | tr -d ' ')
tasks=$(find "$SRC" -mindepth 1 -maxdepth 1 -type d | wc -l | tr -d ' ')

echo "------------------------------------------------"
echo "delivery folder : $NAME"
echo "dataset         : $DATASET"
echo "delivery date   : $DELIV (UTC)"
echo "source          : $SRC"
echo "destination     : $DEST"
echo "local files     : $files (excl .DS_Store)   task dirs: $tasks"
if [ -n "$DRYRUN" ]; then MODE="DRY-RUN (nothing uploaded)"; else MODE="LIVE licensed/formal upload"; fi
echo "mode            : $MODE"
echo "------------------------------------------------"

WORK="$(cd "$(dirname "$0")" && pwd)/.work"; mkdir -p "$WORK"
LOG="$WORK/deliver_${DATASET}_${DELIV}.log"; : > "$LOG"

aws s3 sync "$SRC" "$DEST" --exclude "*.DS_Store" --no-progress --region "$REGION" $DRYRUN 2>&1 | tee "$LOG"
rc=${PIPESTATUS[0]}
[ "$rc" -eq 0 ] || die "aws s3 sync exited with code $rc (see $LOG)"

if [ -n "$DRYRUN" ]; then
  echo "DRY-RUN complete. Nothing was uploaded. Re-run without --dry-run to deliver."
  exit 0
fi

failed=$(grep -c 'upload failed:' "$LOG")
echo "sync done. upload-failed lines in log: $failed"

[ "$VERIFY" -eq 1 ] || { echo "Skipping verify (--no-verify). Dest: $DEST"; exit 0; }

echo "Verifying against S3 (recursive ls may take a minute)..."
got=$(aws s3 ls "$DEST" --recursive --region "$REGION" | wc -l | tr -d ' ')
prefixes=$(aws s3 ls "$DEST" --region "$REGION" | grep -c 'PRE')
bad=$(aws s3 ls "$DEST" --region "$REGION" | awk '{print $2}' | grep -E '[-A-Z.]' || true)
echo "------------------------------------------------"
echo "objects:       got=$got  expected=$files  $([ "$got" -eq "$files" ] && echo OK || echo "MISMATCH(diff=$((got-files)))")"
echo "task prefixes: got=$prefixes  expected=$tasks  $([ "$prefixes" -eq "$tasks" ] && echo OK || echo MISMATCH)"
if [ -n "$bad" ]; then echo "NON-COMPLIANT TOP-LEVEL PREFIXES:"; echo "$bad"; else echo "prefixes:      all snake_case OK"; fi
echo "log failures:  $failed"
echo "------------------------------------------------"
if [ "$got" -eq "$files" ] && [ "$prefixes" -eq "$tasks" ] && [ -z "$bad" ] && [ "$failed" -eq 0 ]; then
  echo "DELIVERY: PASS  -> $DEST"
else
  echo "DELIVERY: FAIL  (re-run deliver.sh — sync is resumable and will fill gaps)"; exit 1
fi
