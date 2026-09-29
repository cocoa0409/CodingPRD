#!/usr/bin/env bash
# Validate a harbor_tasks directory against the Meta Vendor Data format spec.
# Read-only. Usage:
#   bash validate_tasks.sh <harbor_tasks_dir> <vendor> <dataset> [namemap_out.tsv]
# If namemap_out is given, writes a TSV of "old<TAB>normalized_new" for ALL tasks.
set -u
SRC="${1:?usage: validate_tasks.sh <dir> <vendor> <dataset> [namemap.tsv]}"
VENDOR="${2:?vendor required}"; DATASET="${3:?dataset required}"; MAP="${4:-}"
[ -d "$SRC" ] || { echo "ERROR: source dir not found: $SRC" >&2; exit 2; }

normalize() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9_]/_/g'; }

[ -n "$MAP" ] && : > "$MAP"
total=0; compliant=0; need=0; tomlok=0; tomlbad=0; tomlmiss=0
maxlen=0; maxname=""; collision=0
declare -A seen firstfor existing
for d in "$SRC"/*/; do [ -d "$d" ] && existing["$(basename "$d")"]=1; done

for d in "$SRC"/*/; do
  [ -d "$d" ] || continue
  old=$(basename "$d"); total=$((total+1)); new=$(normalize "$old")
  [ -n "$MAP" ] && printf '%s\t%s\n' "$old" "$new" >> "$MAP"
  if [ "$old" = "$new" ]; then compliant=$((compliant+1)); else need=$((need+1)); fi

  t="$d/task.toml"
  if [ ! -f "$t" ]; then echo "  MISSING task.toml: $old"; tomlmiss=$((tomlmiss+1))
  elif grep -qE "name[[:space:]]*=[[:space:]]*\"$old\"" "$t"; then tomlok=$((tomlok+1))
  else echo "  task.toml name != dir name: $old"; tomlbad=$((tomlbad+1)); fi

  if [ -n "${seen[$new]:-}" ]; then
    echo "  COLLISION: '$old' and '${firstfor[$new]}' both normalize to -> $new"; collision=$((collision+1))
  else seen[$new]=1; firstfor[$new]="$old"; fi
  if [ "$old" != "$new" ] && [ -n "${existing[$new]:-}" ]; then
    echo "  COLLISION: renamed '$old' -> '$new' clashes with existing task '$new'"; collision=$((collision+1)); fi

  l=$(printf '%s' "${VENDOR}_${DATASET}_${new}" | wc -c | tr -d ' ')
  [ "$l" -gt "$maxlen" ] && { maxlen=$l; maxname=$new; }
done

dss=$(find "$SRC" -name '.DS_Store' | wc -l | tr -d ' ')
files=$(find "$SRC" -type f | wc -l | tr -d ' ')
echo "---------------------------------------------"
echo "tasks=$total  compliant=$compliant  need_rename=$need"
echo "task.toml: match=$tomlok  mismatch=$tomlbad  missing=$tomlmiss"
echo "collisions=$collision"
echo "max len(${VENDOR}_${DATASET}_<task>)=$maxlen ($maxname)  limit=255  $([ "$maxlen" -le 255 ] && echo OK || echo OVER-LIMIT)"
echo ".DS_Store (excluded on upload)=$dss"
echo "local files=$files   => expected S3 objects=$((files-dss))"
echo "---------------------------------------------"
problems=$((tomlbad+tomlmiss+collision)); [ "$maxlen" -gt 255 ] && problems=$((problems+1))
if [ "$problems" -eq 0 ]; then echo "VALIDATION: PASS"; else echo "VALIDATION: FAIL ($problems blocking issue(s))"; exit 1; fi
