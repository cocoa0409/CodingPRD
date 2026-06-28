#!/usr/bin/env bash
# =============================================================================
#  Harbor 任务 "hydrator"
# =============================================================================
#
#  作用
#  ----
#  把单个 Harbor 任务目录（harbor_tasks/<task-name>/）从"空壳"或"骨架"变成
#  "完整可运行的 Harbor 任务"。
#
#  2 个配置文件 task.toml / README.md 在缺失时按默认模板自动生成（已存在则
#  不动，保留 timeout 等手调值）。整个 harbor_tasks/task_*/ 在仓库根的
#  .gitignore 里被整目录忽略，所以这些文件都不进 git —— 永远以 harbor_utils/
#  和 tasks/ 为唯一真源，跑一遍 prepare.sh / prepare-all.sh 就能完全重建。
#
#  剩余所有运行时文件从 3 个来源拷进去：
#
#      来源 A: harbor_utils/shared/               (通用模板，跨任务共享)
#      来源 B: tasks/<原任务>/                    (任务专属内容，由 task.toml 里
#                                                  [metadata].source_task 指定)
#      来源 C: prd-bench-local-runner/            (测试时 pytest 依赖的 Python 包)
#
#  拷出来的内容全部在任务目录的 .gitignore 里 —— git 不跟踪，每次 prepare.sh
#  跑一遍重新生成，永远以 harbor_utils/ 和原任务为唯一真源。
#
#  使用方式
#  --------
#  单任务：
#      bash harbor_utils/prepare.sh harbor_tasks/<task-name>/
#
#  批量（所有 tasks/task_*/ 一次过转成 harbor_tasks/）：
#      bash harbor_utils/prepare-all.sh
#
#  即把任务目录的绝对/相对路径当参数传进来，剩下的全靠脚本里的约定推断。
#
#  约定
#  ----
#  - 任务目录里必须有 task.toml，且 [metadata].source_task 指向 tasks/<原任务名>
#  - harbor 任务名 == 原任务名（basename 相同）—— 这就是 source_task 的唯一真源
#  - 仓库根 = 这个脚本上一级 (harbor_utils/../)
#  - prd-bench-local-runner/ 永远在仓库根
#  - host 上只要有 bash + rsync（不依赖 python / tomllib）
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

# 这个脚本自己的所在目录（= harbor_utils/）
LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 通用模板根目录（= harbor_utils/shared/）
SHARED_DIR="$LIB_DIR/shared"

# 仓库根（= harbor_utils/ 的上一级）
REPO_ROOT="$(cd "$LIB_DIR/.." && pwd)"

# 测试框架包的源头（永远在仓库根）
LOCAL_RUNNER_DIR="$REPO_ROOT/prd-bench-local-runner"

# 任务名 = 入参 basename。约定 harbor 任务名 == 原任务名，basename 就是
# source_task 的真源（省掉解析 task.toml，也避免"配置写一个、目录叫另一个"）。
# 注意：此处【不】cd 进 HARBOR_TASK_DIR —— 它可能还不存在，而且要先把源任务校验
# 跑完（§2），校验失败就【不建】这个目录。basename 不要求目录存在、且会吃掉尾部
# 斜杠。等 §2 校验全过之后才 mkdir + 用 cd&&pwd 把它规范化成绝对路径。
TASK_NAME="$(basename "$HARBOR_TASK_DIR")"
SOURCE_TASK="tasks/$TASK_NAME"
SOURCE_TASK_DIR="$REPO_ROOT/$SOURCE_TASK"


# -----------------------------------------------------------------------------
# 2. 源任务前置校验（失败就直接退出，绝不 mkdir / 写文件）
# -----------------------------------------------------------------------------
#
# 在生成 / 拷贝任何东西之前，把源任务必须满足的条件一次性检清楚 —— 任何一条不
# 满足就 exit，连 harbor 任务目录都不建，不留半成品现场：
#
#   - tasks/<name>/ 必须存在（harbor 任务名 == 原任务名，basename 即真源）
#   - environment/PRD.md 来源：PRD_FINALIZED.md（优先）或 PRD.md，至少有一个
#   - environment/PRD_EASY.md 来源：PRD_COMPLETED.md，必须有
# -----------------------------------------------------------------------------

if [[ ! -d "$SOURCE_TASK_DIR" ]]; then
  echo "error: source task dir not found: $SOURCE_TASK_DIR" >&2
  echo "       (expected because harbor task name '$TASK_NAME' should match tasks/<name>/)" >&2
  exit 1
fi

WORKSPACE_DIR="$SOURCE_TASK_DIR/workspace"
if [[ ! -f "$WORKSPACE_DIR/PRD_FINALIZED.md" && ! -f "$WORKSPACE_DIR/PRD.md" ]]; then
  echo "error: neither PRD_FINALIZED.md nor PRD.md found in $WORKSPACE_DIR" >&2
  echo "       (need at least one as the source for environment/PRD.md)" >&2
  exit 1
fi
if [[ ! -f "$WORKSPACE_DIR/PRD_COMPLETED.md" ]]; then
  echo "error: PRD_COMPLETED.md not found in $WORKSPACE_DIR" >&2
  echo "       (required as the source for environment/PRD_EASY.md)" >&2
  exit 1
fi

# 校验全过 —— 现在才创建 harbor 任务目录，并把路径规范化成绝对路径
# （后面 cp/rsync 用绝对路径，免得相对路径坑）。
mkdir -p "$HARBOR_TASK_DIR"
HARBOR_TASK_DIR="$(cd "$HARBOR_TASK_DIR" && pwd)"


# -----------------------------------------------------------------------------
# 2.5. 自动生成配置文件（task.toml / README.md）
# -----------------------------------------------------------------------------
#
# 整个 harbor_tasks/task_*/ 被仓库根 .gitignore 整目录忽略，所以这里
# 生成的所有东西都不会被提交 —— 跑一次 prepare-all.sh 就重建。
#
# 已存在的文件一律不动 —— 用户可能手调过 timeout、subtask 名字之类。想强制
# 重新生成就先 `rm` 再跑。
# -----------------------------------------------------------------------------

if [[ ! -f "$HARBOR_TASK_DIR/task.toml" ]]; then
  echo ">> generating task.toml (source_task = tasks/$TASK_NAME)"

  # --- 从源任务 SCAFFOLD.yaml 的 scenario 抽 description / keywords ----------
  # description = scenario 全文（压成单行）
  # keywords    = scenario 第一个冒号之后的部分，按 ',' split，逐个 trim + 去尾句号
  # 兼容两种 YAML 写法：block scalar `scenario: |` 与 inline `scenario: "..."`。
  # 纯 awk/sed，不引入 python/yaml 依赖，跟本脚本"只靠 bash+rsync"的约定一致。
  # 解析不到（scaffold 缺失或无 scenario）就留空，生成 description = "" / keywords = []。
  SCAFFOLD_FILE="$REPO_ROOT/tasks/$TASK_NAME/SCAFFOLD.yaml"
  TASK_DESC=""
  TASK_KEYWORDS=""
  if [[ -f "$SCAFFOLD_FILE" ]]; then
    SCENARIO_RAW="$(awk '
      /^scenario:/ {
        s = $0
        sub(/^scenario:[[:space:]]*/, "", s)
        if (s ~ /^[|>][-+]?[0-9]*[[:space:]]*$/) {          # block scalar `|`
          out = ""
          while ((getline l) > 0) {
            if (l ~ /^[^[:space:]]/) break                   # 下一个顶层 key → 停
            sub(/^[[:space:]]+/, "", l)
            out = out l " "
          }
          print out
        } else {                                             # inline（可能带引号）
          sub(/^"/, "", s); sub(/"[[:space:]]*$/, "", s)
          print s
        }
        exit
      }
    ' "$SCAFFOLD_FILE")"
    # 压空白 + 去首尾空格
    SCENARIO="$(printf '%s' "$SCENARIO_RAW" | tr -s '[:space:]' ' ' | sed 's/^ //; s/ $//')"
    # description：转义 \ 和 "
    TASK_DESC="${SCENARIO//\\/\\\\}"; TASK_DESC="${TASK_DESC//\"/\\\"}"
    # keywords：冒号后 → ',' split → trim + 去尾句号 + 转义 + 包引号
    KW_PART="${SCENARIO#*:}"
    if [[ -n "$KW_PART" ]]; then
      IFS=',' read -ra _KWS <<< "$KW_PART"
      for _raw in "${_KWS[@]}"; do
        kw="$(printf '%s' "$_raw" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//; s/[.[:space:]]*$//')"
        [[ -z "$kw" ]] && continue
        kw="${kw//\\/\\\\}"; kw="${kw//\"/\\\"}"
        [[ -n "$TASK_KEYWORDS" ]] && TASK_KEYWORDS+=", "
        TASK_KEYWORDS+="\"$kw\""
      done
    fi
  fi

  # 交付时间戳：取 prepare 运行当天的日期（只到年月日），动态生成，不写死。
  DELIVERY_DATE="$(date +%F)"

  cat > "$HARBOR_TASK_DIR/task.toml" <<EOF
[task]
name = "prd_to_repo/$TASK_NAME"
keywords = [$TASK_KEYWORDS]

[metadata]
name = "prd_to_repo/$TASK_NAME"
source_task = "tasks/$TASK_NAME"
dataset = "PRD-to-Repo"
dataset_version = "1.2.18"
copyright = "© 2026 KULTA LABS CORPORATION. All rights reserved."
batch_version = 1
delivery_date = "$DELIVERY_DATE"

[verifier]
timeout_sec = 900

[agent]
timeout_sec = 7200

[environment]
build_timeout_sec = 1800
EOF
fi

if [[ ! -f "$HARBOR_TASK_DIR/README.md" ]]; then
  echo ">> generating README.md"
  cat > "$HARBOR_TASK_DIR/README.md" <<EOF
# $TASK_NAME (Harbor)

## Run oracle

\`\`\`bash
harbor run -p harbor_tasks/$TASK_NAME -a oracle -n 8 -k 8
\`\`\`

## Run test

\`\`\`bash
ANTHROPIC_API_KEY=... harbor run \\
  -p harbor_tasks/$TASK_NAME \\
  -a claude-code -m anthropic/claude-opus-4-8
\`\`\`
EOF
fi


# -----------------------------------------------------------------------------
# 3. 打印路径，方便排查
# -----------------------------------------------------------------------------

echo ">> preparing $(basename "$HARBOR_TASK_DIR")"
echo "   source:  $SOURCE_TASK"
echo "   shared:  harbor_utils/shared/"
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
# 跨所有任务复用，单一真源在 harbor_utils/shared/agent/instruction.md。
# -----------------------------------------------------------------------------

cp "$SHARED_DIR/agent/instruction.md" "$HARBOR_TASK_DIR/instruction.md"


# -----------------------------------------------------------------------------
# 6. 填充 environment/ —— agent 的运行环境
# -----------------------------------------------------------------------------
#
# Harbor 用 environment/Dockerfile 给 agent 构建容器。Dockerfile 里显式
# `COPY INSTRUCTION.md /app/` 和 `COPY PRD.md /app/PRD.md`，所以 environment/ 里
# 的这两个文件会进容器的 /app/，agent 进去就能读到。PRD_EASY.md 也拷进
# environment/ 备着，默认不进 /app —— 想跑简单版时改 Dockerfile 的 COPY 源。
#
#   environment/Dockerfile     ← 通用模板 (harbor_utils)
#   environment/.dockerignore  ← 通用模板 (harbor_utils)
#   environment/INSTRUCTION.md ← 任务专属 (原任务的 workspace/)
#   environment/PRD.md         ← 任务专属：PRD_FINALIZED.md（优先）或 PRD.md
#   environment/PRD_EASY.md    ← 任务专属：PRD_COMPLETED.md
#
# 上面三个任务专属文件的来源，§2 已经校验过一定存在，所以这里直接 cp。
# -----------------------------------------------------------------------------

mkdir -p "$HARBOR_TASK_DIR/environment"
cp "$SHARED_DIR/environment/Dockerfile"    "$HARBOR_TASK_DIR/environment/Dockerfile"
cp "$SHARED_DIR/environment/.dockerignore" "$HARBOR_TASK_DIR/environment/.dockerignore"
cp "$SOURCE_TASK_DIR/workspace/INSTRUCTION.md" "$HARBOR_TASK_DIR/environment/INSTRUCTION.md"

# environment/PRD.md：优先 PRD_FINALIZED.md，否则回退 PRD.md（§2 已保证至少有一个）
if [[ -f "$SOURCE_TASK_DIR/workspace/PRD_FINALIZED.md" ]]; then
  cp "$SOURCE_TASK_DIR/workspace/PRD_FINALIZED.md" "$HARBOR_TASK_DIR/environment/PRD.md"
  echo ">> using PRD_FINALIZED.md as environment/PRD.md"
else
  cp "$SOURCE_TASK_DIR/workspace/PRD.md" "$HARBOR_TASK_DIR/environment/PRD.md"
  echo ">> using PRD.md as environment/PRD.md"
fi

# environment/PRD_EASY.md：来源 PRD_COMPLETED.md（§2 已保证存在）
cp "$SOURCE_TASK_DIR/workspace/PRD_COMPLETED.md" "$HARBOR_TASK_DIR/environment/PRD_EASY.md"
echo ">> using PRD_COMPLETED.md as environment/PRD_EASY.md"


# -----------------------------------------------------------------------------
# 7. 填充 tests/ —— 评测脚本与测试代码
# -----------------------------------------------------------------------------
#
# Harbor 在评测阶段会把 tests/ 整个挂到容器的 /tests，然后跑 tests/test.sh。
#
#   tests/test.sh                ← 通用模板 (harbor_utils)：调 prd-bench-local-run → 转 reward
#   tests/results_to_reward.py   ← 通用模板 (harbor_utils)：local-runner 的 results.json → Harbor reward.json
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
#   solution/solve.sh        ← 通用模板 (harbor_utils)：cp /solution/implementation/* /app/
#   solution/implementation/ ← 任务专属 (原任务的 workspace/implementation/)
# -----------------------------------------------------------------------------

mkdir -p "$HARBOR_TASK_DIR/solution"
cp "$SHARED_DIR/solution/solve.sh" "$HARBOR_TASK_DIR/solution/solve.sh"
chmod +x "$HARBOR_TASK_DIR/solution/solve.sh"
"${RSYNC[@]}" "$SOURCE_TASK_DIR/workspace/implementation/" \
              "$HARBOR_TASK_DIR/solution/implementation/"

# cp 进来的参考实现里常夹带不属于实现本身的产物，删掉，免得混进对外交付：
#   - result*.json   上次跑测试遗留的结果（results.json / results.1.json / … /
#                    results.8.json）。§4 的全局 rsync 只 exclude 了精确名
#                    results.json，带数字后缀的会漏网，这里补删。
#   - 隐藏文件/目录   .env / .DS_Store / .pytest_cache / .git 之类。递归删整棵
#                    implementation 树里所有以 . 开头的条目（-mindepth 1 保证不
#                    误伤 implementation 自身；-prune 命中隐藏目录就整个删掉、
#                    不再往里钻）。
find "$HARBOR_TASK_DIR/solution/implementation" -type f -name 'result*.json' -delete
find "$HARBOR_TASK_DIR/solution/implementation" -mindepth 1 -name '.*' -prune -exec rm -rf {} +
echo ">> removed result*.json + hidden files from solution/implementation"


# -----------------------------------------------------------------------------
# 9. 完事
# -----------------------------------------------------------------------------

echo "<< prepared $(basename "$HARBOR_TASK_DIR")"
