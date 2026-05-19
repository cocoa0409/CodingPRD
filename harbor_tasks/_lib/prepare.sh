#!/usr/bin/env bash
# =============================================================================
#  Harbor 任务 "hydrator"
# =============================================================================
#
#  作用
#  ----
#  把一个 Harbor 任务目录（harbor_tasks/<task-name>/）从"骨架"变成"完整可运行的
#  Harbor 任务"。骨架里只有 4 个 committed 文件（task.toml / prepare.sh /
#  .gitignore / README.md），这个脚本会把其余文件
#  从 3 个不同的来源拷进去：
#
#      来源 A: harbor_tasks/_lib/shared/          (通用模板，跨任务共享)
#      来源 B: tasks/<原任务>/                    (任务专属内容，由 task.toml 里
#                                                  [metadata].source_task 指定)
#      来源 C: prd-bench-local-runner/            (测试时 pytest 依赖的 Python 包)
#
#  拷出来的内容全部在任务目录的 .gitignore 里 —— git 不跟踪，每次 prepare.sh
#  跑一遍重新生成，永远以 _lib/ 和原任务为唯一真源。
#
#  使用方式
#  --------
#  每个 harbor_tasks/<task-name>/prepare.sh 是个一行 wrapper:
#      exec ../_lib/prepare.sh "$(dirname "$0")"
#
#  即把任务目录的绝对路径当参数传进来，剩下的全靠这个脚本里的约定推断。
#
#  约定
#  ----
#  - 任务目录里必须有 task.toml，且 [metadata].source_task 指向 tasks/<原任务名>
#  - 仓库根 = 这个脚本上两级 (harbor_tasks/_lib/../../)
#  - prd-bench-local-runner/ 永远在仓库根
#  - host 上要有 python3 (>=3.11，自带 tomllib)
# =============================================================================

set -euo pipefail


# -----------------------------------------------------------------------------
# 1. 参数解析与路径推断
# -----------------------------------------------------------------------------

# 调用方传进来的第一个参数：harbor 任务目录的路径
HARBOR_TASK_DIR="${1:-}"
if [[ -z "$HARBOR_TASK_DIR" ]]; then
  echo "usage: $0 <harbor-task-dir>" >&2
  exit 2
fi
# 转成绝对路径，免得后面 cp/rsync 时被相对路径坑
HARBOR_TASK_DIR="$(cd "$HARBOR_TASK_DIR" && pwd)"

# 这个脚本自己的所在目录（= harbor_tasks/_lib/）
LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 通用模板根目录（= harbor_tasks/_lib/shared/）
SHARED_DIR="$LIB_DIR/shared"

# 仓库根（= harbor_tasks/_lib/ 的上两级）
REPO_ROOT="$(cd "$LIB_DIR/../.." && pwd)"

# 测试框架包的源头（永远在仓库根）
LOCAL_RUNNER_DIR="$REPO_ROOT/prd-bench-local-runner"


# -----------------------------------------------------------------------------
# 2. 读 task.toml，确定本任务对应哪个"原任务"
# -----------------------------------------------------------------------------
#
# task.toml 里有 [metadata].source_task，例子：
#   [metadata]
#   source_task = "tasks/task_0001_food_delivery_for_harbor"
#
# 这一行告诉 hydrator：本 Harbor 任务的 PRD / test_suite / 参考实现要去哪儿拿。
# task.toml 本来就是 Harbor 框架要求的文件，复用它做单一真源，避免和别处重复。
# -----------------------------------------------------------------------------

TASK_TOML="$HARBOR_TASK_DIR/task.toml"
if [[ ! -f "$TASK_TOML" ]]; then
  echo "error: $TASK_TOML missing" >&2
  exit 1
fi

SOURCE_TASK="$(python3 - "$TASK_TOML" <<'PY'
import sys, tomllib
with open(sys.argv[1], "rb") as f:
    cfg = tomllib.load(f)
try:
    print(cfg["metadata"]["source_task"])
except KeyError:
    sys.exit("task.toml missing [metadata].source_task")
PY
)" || exit 1

SOURCE_TASK_DIR="$REPO_ROOT/$SOURCE_TASK"
if [[ ! -d "$SOURCE_TASK_DIR" ]]; then
  echo "error: source task dir not found: $SOURCE_TASK_DIR" >&2
  exit 1
fi


# -----------------------------------------------------------------------------
# 3. 打印路径，方便排查
# -----------------------------------------------------------------------------

echo ">> preparing $(basename "$HARBOR_TASK_DIR")"
echo "   source:  $SOURCE_TASK"
echo "   shared:  harbor_tasks/_lib/shared/"
echo "   runner:  prd-bench-local-runner/"


# -----------------------------------------------------------------------------
# 4. rsync 选项（拷目录时统一忽略的"垃圾"）
# -----------------------------------------------------------------------------
#
# --delete            目的端有、源端没的文件也删掉（保证同步而非堆积）
# --exclude __pycache__/*.pyc/*.egg-info/.venv   Python 的临时产物
# --exclude *.db      老的 SQLite，可能是上次跑测试遗留
# --exclude results.json  上次跑出来的结果
# -----------------------------------------------------------------------------

RSYNC=(rsync -a --delete
  --exclude __pycache__
  --exclude '*.egg-info'
  --exclude '.venv'
  --exclude '*.pyc'
  --exclude '*.db'
  --exclude 'results.json')


# -----------------------------------------------------------------------------
# 5. 填充 instruction.md —— Harbor 给模型的入口 prompt
# -----------------------------------------------------------------------------
#
# Harbor 起 trial 时读 instruction.md 当 agent 的 prompt 注入。我们用一份
# 共享的通用模板（讲方法论、指引模型去读 /app/INSTRUCTION.md 和 /app/PRD.md），
# 跨所有任务复用，单一真源在 _lib/shared/agent/instruction.md。
# -----------------------------------------------------------------------------

cp "$SHARED_DIR/agent/instruction.md" "$HARBOR_TASK_DIR/instruction.md"


# -----------------------------------------------------------------------------
# 6. 填充 environment/ —— agent 的运行环境
# -----------------------------------------------------------------------------
#
# Harbor 用 environment/Dockerfile 给 agent 构建容器。Dockerfile 里有
# `COPY . /app/`，所以 environment/ 里的 INSTRUCTION.md 和 PRD.md 会被一起
# 拷进容器的 /app/，agent 进去就能读到。
#
#   environment/Dockerfile     ← 通用模板 (_lib)
#   environment/.dockerignore  ← 通用模板 (_lib)
#   environment/INSTRUCTION.md ← 任务专属 (原任务的 workspace/)
#   environment/PRD.md         ← 任务专属 (原任务的 workspace/)
# -----------------------------------------------------------------------------

mkdir -p "$HARBOR_TASK_DIR/environment"
cp "$SHARED_DIR/environment/Dockerfile"    "$HARBOR_TASK_DIR/environment/Dockerfile"
cp "$SHARED_DIR/environment/.dockerignore" "$HARBOR_TASK_DIR/environment/.dockerignore"
cp "$SOURCE_TASK_DIR/workspace/INSTRUCTION.md" "$HARBOR_TASK_DIR/environment/INSTRUCTION.md"
cp "$SOURCE_TASK_DIR/workspace/PRD.md"         "$HARBOR_TASK_DIR/environment/PRD.md"


# -----------------------------------------------------------------------------
# 7. 填充 tests/ —— 评测脚本与测试代码
# -----------------------------------------------------------------------------
#
# Harbor 在评测阶段会把 tests/ 整个挂到容器的 /tests，然后跑 tests/test.sh。
#
#   tests/test.sh                ← 通用模板 (_lib)：调 prd-bench-local-run → 转 reward
#   tests/results_to_reward.py   ← 通用模板 (_lib)：local-runner 的 results.json → Harbor reward.json
#   tests/test_suite/            ← 任务专属 (原任务)：12 个 pytest 模块
#   tests/test_helpers/          ← 任务专属 (原任务)：API client / fixtures / 等
#   tests/prd-bench-local-runner/← 仓库根的测试框架包 (test_helpers 依赖它)
# -----------------------------------------------------------------------------

mkdir -p "$HARBOR_TASK_DIR/tests"
cp "$SHARED_DIR/tests/test.sh"              "$HARBOR_TASK_DIR/tests/test.sh"
cp "$SHARED_DIR/tests/results_to_reward.py" "$HARBOR_TASK_DIR/tests/results_to_reward.py"
chmod +x "$HARBOR_TASK_DIR/tests/test.sh"

"${RSYNC[@]}" "$SOURCE_TASK_DIR/test_suite/"   "$HARBOR_TASK_DIR/tests/test_suite/"
"${RSYNC[@]}" "$SOURCE_TASK_DIR/test_helpers/" "$HARBOR_TASK_DIR/tests/test_helpers/"
"${RSYNC[@]}" "$LOCAL_RUNNER_DIR/"             "$HARBOR_TASK_DIR/tests/prd-bench-local-runner/"


# -----------------------------------------------------------------------------
# 8. 填充 solution/ —— 给 "oracle" agent 用的参考答案
# -----------------------------------------------------------------------------
#
# Harbor 的 oracle agent 不调模型，直接跑 solution/solve.sh，把里头的参考
# 实现搬到 /app/implementation/。用来冒烟测：跑一遍 oracle，如果 reward=1.0
# 说明评测链路通了；reward<1.0 说明 test.sh / 参考实现自己有问题。
#
#   solution/solve.sh        ← 通用模板 (_lib)：cp /solution/implementation/* /app/
#   solution/implementation/ ← 任务专属 (原任务的 workspace/implementation/)
# -----------------------------------------------------------------------------

mkdir -p "$HARBOR_TASK_DIR/solution"
cp "$SHARED_DIR/solution/solve.sh" "$HARBOR_TASK_DIR/solution/solve.sh"
chmod +x "$HARBOR_TASK_DIR/solution/solve.sh"
"${RSYNC[@]}" "$SOURCE_TASK_DIR/workspace/implementation/" \
              "$HARBOR_TASK_DIR/solution/implementation/"


# -----------------------------------------------------------------------------
# 9. 完事
# -----------------------------------------------------------------------------

echo "<< prepared $(basename "$HARBOR_TASK_DIR")"
