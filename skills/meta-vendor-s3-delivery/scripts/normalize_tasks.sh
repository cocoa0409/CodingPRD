#!/usr/bin/env bash
# Normalize task directory names to the vendor charset [a-z0-9_] IN PLACE, and
# keep each task.toml in sync (the dir name is also embedded in the toml's name
# field, e.g. name = "security/<dir>", so renaming the dir alone would desync it).
#
# This mutates the SOURCE tree (renames dirs + rewrites task.toml). It is the
# "fix names at the source" alternative to upload_delivery.sh's on-the-fly
# normalization — use it when you want the local dataset itself to be compliant
# (e.g. before committing/sharing), not just the uploaded copy.
#
# Defaults to DRY-RUN. Pass --apply to actually rename. Aborts before touching
# anything if normalization would collide. No bash-4 features (runs on stock
# macOS /bin/bash 3.2).
#
# Usage:
#   bash normalize_tasks.sh <harbor_tasks_dir> [--apply]
set -u
SRC="${1:?usage: normalize_tasks.sh <harbor_tasks_dir> [--apply]}"
APPLY=""
[ "${2:-}" = "--apply" ] && APPLY=1
[ -d "$SRC" ] || { echo "ERROR: source dir not found: $SRC" >&2; exit 2; }

normalize() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9_]/_/g'; }
escape_re() { printf '%s' "$1" | sed 's/[.[\*^$/]/\\&/g'; }  # escape BRE metachars in old name

# ---- collision pre-check (abort before renaming anything) ----
collision=0
map="$(mktemp)"; trap 'rm -f "$map"' EXIT
for d in "$SRC"/*/; do
  [ -d "$d" ] || continue
  old=$(basename "$d"); new=$(normalize "$old")
  printf '%s\t%s\n' "$new" "$old" >> "$map"
  # a non-compliant name that maps onto a DIFFERENT existing dir
  if [ "$old" != "$new" ] && [ -d "$SRC/$new" ]; then
    echo "COLLISION: '$old' -> '$new' clashes with existing task '$new'" >&2; collision=1
  fi
done
# two distinct old names normalizing to the same new name
dups=$(cut -f1 "$map" | sort | uniq -d)
if [ -n "$dups" ]; then
  while IFS= read -r n; do
    [ -z "$n" ] && continue
    olds=$(awk -F'\t' -v k="$n" '$1==k{printf "%s ",$2}' "$map")
    echo "COLLISION: [$olds] all normalize to -> $n" >&2; collision=1
  done <<EOF
$dups
EOF
fi
[ "$collision" -eq 0 ] || { echo "Aborting due to collisions. Resolve names at the source first." >&2; exit 1; }

total=0; renamed=0; tomlrw=0; tomlmiss=0
for d in "$SRC"/*/; do
  [ -d "$d" ] || continue
  old=$(basename "$d"); total=$((total+1)); new=$(normalize "$old")
  [ "$old" = "$new" ] && continue
  renamed=$((renamed+1))
  t="$SRC/$old/task.toml"
  if [ -f "$t" ]; then
    tomlrw=$((tomlrw+1))
    if [ -n "$APPLY" ]; then
      # replace the exact old name string wherever it appears (covers name = "<old>"
      # and name = "security/<old>"); only the dir-name token ever matches.
      tmp="$t.tmp.$$"
      sed "s/$(escape_re "$old")/$new/g" "$t" > "$tmp" && mv "$tmp" "$t"
    fi
  else
    tomlmiss=$((tomlmiss+1))
  fi
  if [ -n "$APPLY" ]; then
    mv "$SRC/$old" "$SRC/$new"
    echo "renamed: $old -> $new"
  else
    echo "would rename: $old -> $new$([ -f "$t" ] && echo '  (+task.toml)' || echo '  (no task.toml)')"
  fi
done

echo "---------------------------------------------"
echo "tasks=$total  to_rename=$renamed  task.toml_synced=$tomlrw  task.toml_missing=$tomlmiss"
if [ -z "$APPLY" ]; then
  echo "DRY-RUN only. Re-run with --apply to perform the rename."
else
  bad=0
  for d in "$SRC"/*/; do [ -d "$d" ] || continue; n=$(basename "$d")
    printf '%s' "$n" | grep -qE '^[a-z0-9_]+$' || { echo "STILL NON-COMPLIANT: $n"; bad=$((bad+1)); }; done
  [ "$bad" -eq 0 ] && echo "DONE: all dir names now match ^[a-z0-9_]+$" || { echo "FAIL: $bad non-compliant name(s) remain"; exit 1; }
fi
