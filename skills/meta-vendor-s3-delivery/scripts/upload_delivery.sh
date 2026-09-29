#!/usr/bin/env bash
# Upload a harbor_tasks delivery to a Meta vendor S3 bucket per the format spec.
# - Normalizes non-compliant task names to snake_case and rewrites task.toml name.
# - Uses per-task `aws s3 sync` => idempotent + resumable; .DS_Store excluded.
# - Aborts before any upload if normalization would cause a name collision.
#
# Usage:
#   bash upload_delivery.sh <harbor_tasks_dir> <bucket> <licensed|sample> \
#        <dataset> <delivery_YYYY-MM-DD> [region] [--dryrun]
#
# ALWAYS run with --dryrun first on anything large/unfamiliar. Uploading to a
# real vendor bucket is outward-facing; confirm class/dataset/date with the user.
set -u
SRC="${1:?usage: upload_delivery.sh <dir> <bucket> <licensed|sample> <dataset> <YYYY-MM-DD> [region] [--dryrun]}"
BUCKET="${2:?bucket required}"; CLASS="${3:?class required}"
DATASET="${4:?dataset required}"; DELIV="${5:?delivery date required}"
REGION="${6:-us-east-2}"; DRYRUN=""
[ "${6:-}" = "--dryrun" ] && { DRYRUN="--dryrun"; REGION="us-east-2"; }
[ "${7:-}" = "--dryrun" ] && DRYRUN="--dryrun"

[ -d "$SRC" ] || { echo "ERROR: source not found: $SRC" >&2; exit 2; }
case "$CLASS" in licensed|sample) ;; *) echo "ERROR: class must be 'licensed' or 'sample'" >&2; exit 2;; esac
printf '%s' "$DELIV" | grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2}$' \
  || { echo "ERROR: delivery date must be ISO8601 UTC date YYYY-MM-DD: $DELIV" >&2; exit 2; }

DEST="s3://${BUCKET}/${CLASS}/dataset=${DATASET}/delivery=${DELIV}"
WORK="$(cd "$(dirname "$0")" && pwd)/.work"; mkdir -p "$WORK/tomls"
LOG="$WORK/upload_${DATASET}_${DELIV}.log"; META="$LOG.meta"
: > "$LOG"; echo "START $(date -u +%FT%TZ) dest=$DEST dryrun=${DRYRUN:-no}" > "$META"

normalize() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9_]/_/g'; }
escape_dot() { printf '%s' "$1" | sed 's/\./\\./g'; }   # task names only ever contain . - A-Z besides [a-z0-9_]

# ---- collision pre-check (abort before touching S3) ----
declare -A seen existing; collision=0
for d in "$SRC"/*/; do [ -d "$d" ] && existing["$(basename "$d")"]=1; done
for d in "$SRC"/*/; do
  [ -d "$d" ] || continue; old=$(basename "$d"); new=$(normalize "$old")
  if [ -n "${seen[$new]:-}" ]; then echo "COLLISION: two tasks map to '$new'" >&2; collision=1; fi; seen[$new]=1
  if [ "$old" != "$new" ] && [ -n "${existing[$new]:-}" ]; then
    echo "COLLISION: '$old' -> '$new' clashes with existing task '$new'" >&2; collision=1; fi
done
[ "$collision" -eq 0 ] || { echo "Aborting due to collisions. Resolve names at the source first." >&2; exit 1; }

n=0
for d in "$SRC"/*/; do
  [ -d "$d" ] || continue
  old=$(basename "$d"); new=$(normalize "$old"); n=$((n+1))
  echo ">>> [$n] $old -> $new" >> "$LOG"
  if [ "$old" = "$new" ]; then
    aws s3 sync "$SRC/$old" "$DEST/$new/" --exclude "*.DS_Store" --no-progress --region "$REGION" $DRYRUN >> "$LOG" 2>&1
  else
    # content first (skip toml; we upload a corrected one), then fixed toml
    aws s3 sync "$SRC/$old" "$DEST/$new/" --exclude "*.DS_Store" --exclude "task.toml" --no-progress --region "$REGION" $DRYRUN >> "$LOG" 2>&1
    if [ -f "$SRC/$old/task.toml" ]; then
      sed "s/$(escape_dot "$old")/$new/g" "$SRC/$old/task.toml" > "$WORK/tomls/$new.task.toml"
      aws s3 cp "$WORK/tomls/$new.task.toml" "$DEST/$new/task.toml" --no-progress --region "$REGION" $DRYRUN >> "$LOG" 2>&1
    fi
  fi
done

echo "DONE $(date -u +%FT%TZ)" >> "$META"
echo "upload_lines=$(grep -c 'upload:' "$LOG")" >> "$META"
echo "failed_lines=$(grep -c 'upload failed:' "$LOG")" >> "$META"
echo "tasks_processed=$n" >> "$META"
echo "Log: $LOG"
echo "Done. tasks=$n  uploaded(or dryrun)_lines=$(grep -c 'upload:' "$LOG")  failed=$(grep -c 'upload failed:' "$LOG")"
echo "Next: bash verify_delivery.sh \"$SRC\" $BUCKET $CLASS $DATASET $DELIV $REGION \"$LOG\""
