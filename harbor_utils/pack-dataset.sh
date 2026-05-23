#!/usr/bin/env bash
# =============================================================================
#  Harbor 数据集打包器
# =============================================================================
#
#  作用
#  ----
#  把 harbor_tasks/ 下所有已 hydrate 的 task_*/ 一次性聚成一个 Harbor 数据集
#  （生成 harbor_tasks/dataset.toml）。之后就能一条命令把整批任务跑起来：
#
#      harbor run -p harbor_tasks/ -a oracle -k 8 -n 16
#
#  为什么 dataset.toml 放在 harbor_tasks/ 里？
#  -------------------------------------------
#  Harbor 运行/同步时按"dataset.toml 同级目录里的直接子目录"来定位每个 task
#  （见 harbor.cli.sync:sync_dataset → dataset_dir.iterdir()）。也就是说，
#  dataset.toml 的同级目录里必须有一堆带 task.toml 的子目录才能解析。
#  harbor_tasks/ 正好满足。
#
#  用法
#  ----
#      bash harbor_utils/pack_dataset.sh                          # 默认
#      bash harbor_utils/pack_dataset.sh -n my-org/my-bench       # 自定义名字
#      bash harbor_utils/pack_dataset.sh -d "subset desc"         # 自定义描述
#
#  幂等性
#  ------
#  - dataset.toml 不存在：写入 [dataset] 头，再用 `harbor add` 注册所有 task_*
#  - dataset.toml 存在：跳过头部生成，`harbor add` 自身幂等（已存在的 task
#    digest 变了会更新，没变会跳过；新 task 会追加）
#  - 跑完会再调一次 `harbor sync` 把所有 task 的 digest 跟当前盘上内容对齐
# =============================================================================

set -euo pipefail


# -----------------------------------------------------------------------------
# 1. 路径推断 & 参数解析
# -----------------------------------------------------------------------------

LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$LIB_DIR/.." && pwd)"
HARBOR_DIR="$REPO_ROOT/harbor_tasks"
DATASET_TOML="$HARBOR_DIR/dataset.toml"

DATASET_NAME="prd-to-repo/harbor-tasks"
DESCRIPTION="All hydrated prd-bench harbor tasks."

usage() {
  sed -n '2,30p' "$0"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -n|--name)         DATASET_NAME="$2"; shift 2;;
    -d|--description)  DESCRIPTION="$2"; shift 2;;
    -h|--help)         usage; exit 0;;
    *) echo "unknown arg: $1" >&2; usage >&2; exit 2;;
  esac
done


# -----------------------------------------------------------------------------
# 2. 前置检查
# -----------------------------------------------------------------------------

if ! command -v harbor >/dev/null 2>&1; then
  echo "error: harbor CLI not found on PATH" >&2
  exit 1
fi

if [[ ! -d "$HARBOR_DIR" ]]; then
  echo "error: $HARBOR_DIR not found" >&2
  exit 1
fi

# 收集所有 hydrated 任务（必须有 task.toml）。没 task.toml 的目录说明没跑过
# prepare.sh，跳过它并提醒用户先 hydrate。
TASK_DIRS=()
SKIPPED=()
while IFS= read -r d; do
  name="$(basename "$d")"
  if [[ -f "$d/task.toml" ]]; then
    TASK_DIRS+=("$name")
  else
    SKIPPED+=("$name")
  fi
done < <(find "$HARBOR_DIR" -mindepth 1 -maxdepth 1 -type d -name 'task_*' | sort)

total=${#TASK_DIRS[@]}
if (( total == 0 )); then
  echo "error: no hydrated harbor tasks under $HARBOR_DIR" >&2
  echo "       run 'bash harbor_utils/prepare-all.sh' first." >&2
  exit 1
fi

if (( ${#SKIPPED[@]} > 0 )); then
  echo "warn: skipping ${#SKIPPED[@]} un-hydrated task dir(s) (no task.toml):" >&2
  for s in "${SKIPPED[@]}"; do echo "      - $s" >&2; done
  echo "      run 'bash harbor_utils/prepare-all.sh' to fix." >&2
fi


# -----------------------------------------------------------------------------
# 3. 初始化 dataset.toml（缺则建）
# -----------------------------------------------------------------------------
#
# 不调 `harbor dataset init`：那个命令会顺手在同级生成一个 README.md，
# 而 harbor_tasks/ 下我们不想多出这种文件。我们自己写最小骨架就够 —— harbor
# add / sync / run 都只读 [dataset] 头 + [[tasks]] 块。
# -----------------------------------------------------------------------------

if [[ ! -f "$DATASET_TOML" ]]; then
  echo ">> creating $DATASET_TOML (name = $DATASET_NAME)"
  cat > "$DATASET_TOML" <<TOML
[dataset]
name = "$DATASET_NAME"
description = "$DESCRIPTION"
authors = []
keywords = []

tasks = []
TOML
else
  echo ">> updating existing $DATASET_TOML"
fi


# -----------------------------------------------------------------------------
# 4. 注册所有任务 & 对齐 digest
# -----------------------------------------------------------------------------
#
# harbor add 用相对路径，cd 到 harbor_tasks/ 里跑 —— 这样 add 写进
# dataset.toml 的 task name 就是 "harbor_tasks/task_xxx" 的简洁形式
# （由各 task.toml 的 [task].name 决定，prepare.sh 设的就是这个值）。
#
# add 之后再 sync 一次，确保 digest 跟盘上当前内容对齐（若 add 已经写过
# 最新 digest，sync 就是 no-op）。
# -----------------------------------------------------------------------------

echo ">> packing $total task(s) into dataset"
(
  cd "$HARBOR_DIR"
  harbor add "${TASK_DIRS[@]}" --to ./dataset.toml | tail -n 5
)

echo ">> syncing digests"
harbor sync "$DATASET_TOML" 2>&1 | tail -n 3


# -----------------------------------------------------------------------------
# 5. 完事 —— 提示下一步
# -----------------------------------------------------------------------------

echo
echo "<< dataset ready: $DATASET_TOML"
echo "   contains $total task(s) as '$DATASET_NAME'"
echo
echo "   run oracle 8x each across the whole dataset:"
echo "       harbor run -p harbor_tasks/ -a oracle -k 8 -n 8"
echo
echo "   subset via glob:"
echo "       harbor run -p harbor_tasks/ -a oracle -k 8 -n 8 -i 'task_01*'"
