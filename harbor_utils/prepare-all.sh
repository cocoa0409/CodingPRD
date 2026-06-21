#!/usr/bin/env bash
# =============================================================================
#  Harbor 批量 hydrator
# =============================================================================
#
#  作用
#  ----
#  扫描 <repo>/tasks/task_*/，对每个任务调 harbor_utils/prepare.sh 做一次完整
#  hydrate（目录由 prepare.sh 在源任务校验通过后自己建，校验失败不留空目录）。
#  适合"一次性把整个仓库的任务全转成 Harbor 格式"。
#
#  用法
#  ----
#      bash harbor_utils/prepare-all.sh
#
#  约定
#  ----
#  - harbor 任务名 == 原任务名（basename 相同）
#  - 单任务失败不中断整个 run；最后汇总并以非零退出码反映失败数
#  - 已存在的 harbor 任务也会重跑：committed 配置文件（task.toml /
#    .gitignore / README.md）保留用户改动，其它 rsync 同步源
# =============================================================================

set -euo pipefail

LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$LIB_DIR/.." && pwd)"
TASKS_DIR="$REPO_ROOT/tasks"
HARBOR_DIR="$REPO_ROOT/harbor_tasks"

if [[ ! -d "$TASKS_DIR" ]]; then
  echo "error: $TASKS_DIR not found" >&2
  exit 1
fi

# 收集任务列表，按名字排序（输出可预测，方便对比 run 之间的差异）。
# macOS 自带 bash 3.2 没有 mapfile，所以用 while-read 兼容写法。
TASKS=()
while IFS= read -r d; do
  TASKS+=("$d")
done < <(find "$TASKS_DIR" -mindepth 1 -maxdepth 1 -type d -name 'task_*' | sort)
total=${#TASKS[@]}
if (( total == 0 )); then
  echo "no tasks found under $TASKS_DIR"
  exit 0
fi

echo ">> preparing $total harbor tasks under $HARBOR_DIR/"
echo

ok=0
fail=0
failed=()

for i in "${!TASKS[@]}"; do
  src="${TASKS[$i]}"
  task_name="$(basename "$src")"
  harbor_task="$HARBOR_DIR/$task_name"

  # 不在这里 mkdir —— prepare.sh 会先做源任务校验，校验通过后才自己建目录
  # （mkdir -p 连 harbor_tasks/ 父目录一起建）。这样校验失败的任务连空目录都不留。
  printf "[%3d/%d] %s\n" "$((i+1))" "$total" "$task_name"

  if bash "$LIB_DIR/prepare.sh" "$harbor_task"; then
    echo "         -> ok"
    ok=$((ok+1))
  else
    echo "         -> FAILED"
    fail=$((fail+1))
    failed+=("$task_name")
  fi
done

echo
echo "============================================================"
echo "  succeeded: $ok / $total"
echo "  failed:    $fail"
if (( fail > 0 )); then
  echo "  failed tasks:"
  for t in "${failed[@]}"; do echo "    - $t"; done
fi
echo "============================================================"

(( fail == 0 ))
