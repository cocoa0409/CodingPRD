#!/bin/bash
set -euo pipefail

# ============================================================
# prd-bench-entrance: single task, context-isolated per step
# Usage: ./run_entrance.sh "场景描述..."
# ============================================================

SCENARIO="$1"
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

CLAUDE="claude -p --dangerously-skip-permissions"
FIX_ITER=0

# ── Step 1: Determine task name ──────────────────────────────
max_index=$(ls -d ./tasks/task_[0-9][0-9][0-9][0-9]_* 2>/dev/null | \
  sed 's/.*task_\([0-9]*\)_.*/\1/' | sort -n | tail -1 || true)
next_index=$(printf "%04d" $(( ${max_index:-0} + 1 )))

# Ask claude to pick a short label from the scenario
short_label=$($CLAUDE "Given this scenario description, output ONLY a short snake_case label (2-3 words, no explanation, no quotes):
${SCENARIO}" | tr -d '[:space:]')

TASK_NAME="task_${next_index}_${short_label}"
TASK_DIR="./tasks/${TASK_NAME}"

echo "=== Task: ${TASK_NAME} ==="
mkdir -p "${TASK_DIR}/workspace"

# ── Step 2: Generate Scaffold ────────────────────────────────
echo "=== Step 2: Generating SCAFFOLD.yaml ==="
$CLAUDE "你是 prd-bench-scaffold-generator。请读取 ${PROJECT_ROOT}/skills/prd-bench-scaffold-generator/SKILL.md 了解完整生成规范，然后根据以下场景描述生成完整的 SCAFFOLD.yaml，保存到 ${TASK_DIR}/SCAFFOLD.yaml。

场景描述（原封不动）：
${SCENARIO}"

echo "=== Step 2 done: ${TASK_DIR}/SCAFFOLD.yaml ==="

# ── Step 3: Copy shared files ────────────────────────────────
echo "=== Step 3: Copying shared files ==="
cp ./Dockerfile.test "${TASK_DIR}/Dockerfile.test"
cp ./INSTRUCTION.md "${TASK_DIR}/workspace/INSTRUCTION.md"

# ── Step 4: Generate PRD ─────────────────────────────────────
echo "=== Step 4: Generating PRD.md ==="
$CLAUDE "你是 prd-bench-doc-generator。请读取 ${PROJECT_ROOT}/skills/prd-bench-doc-generator/SKILL.md 了解完整生成规范，然后读取 ${TASK_DIR}/SCAFFOLD.yaml 作为输入，生成 PRD 文档，保存到 ${TASK_DIR}/workspace/PRD.md。"

echo "=== Step 4 done: ${TASK_DIR}/workspace/PRD.md ==="

# ── Step 5: Generate Unit Tests ──────────────────────────────
echo "=== Step 5: Generating unit tests ==="
$CLAUDE "你是 prd-bench-unit-test-generator。请读取 ${PROJECT_ROOT}/skills/prd-bench-unit-test-generator/SKILL.md 了解完整生成规范，然后读取 ${TASK_DIR}/SCAFFOLD.yaml 和 ${TASK_DIR}/workspace/PRD.md，在 ${TASK_DIR}/test_helpers/ 和 ${TASK_DIR}/test_suite/ 下生成完整的测试代码。测试必须严格对齐 SCAFFOLD 和 PRD 的每一条规则。"

echo "=== Step 5 done: test_helpers/ + test_suite/ ==="

# ── Step 6: Generate Implementation ──────────────────────────
echo "=== Step 6: Generating implementation ==="
$CLAUDE "你是 prd-bench-implementation-generator。请读取 ${PROJECT_ROOT}/skills/prd-bench-implementation-generator/SKILL.md 了解完整生成规范，然后读取以下三个文件：
- ${TASK_DIR}/workspace/INSTRUCTION.md
- ${TASK_DIR}/SCAFFOLD.yaml
- ${TASK_DIR}/workspace/PRD.md
在 ${TASK_DIR}/workspace/implementation/ 下生成完整的 Python + Flask 实现，包含 Dockerfile。"

echo "=== Step 6 done: implementation/ ==="

# ── Step 7: Test & Iterate ───────────────────────────────────
RESULTS_FILE="${TASK_DIR}/workspace/implementation/results.json"

while true; do
  FIX_ITER=$((FIX_ITER + 1))
  echo "=== Iteration $FIX_ITER: Running tests ==="

  prd-bench-docker-run \
    --task-dir "$TASK_DIR" \
    --impl-dir "$TASK_DIR/workspace/implementation" \
    --results-file "$RESULTS_FILE" || true

  # Check results
  if [ ! -f "$RESULTS_FILE" ]; then
    echo "ERROR: results.json not found, docker run may have failed"
    # Try to fix build errors
    $CLAUDE "Docker 测试运行失败，results.json 未生成。请检查 ${TASK_DIR}/workspace/implementation/ 下的 Dockerfile 和代码，修复构建或启动错误。确保服务能在 PORT 环境变量指定的端口上启动并绑定 0.0.0.0。"
    continue
  fi

  passed=$(python3 -c "import json; print(json.load(open('${RESULTS_FILE}'))['passed'])")
  total=$(python3 -c "import json; print(json.load(open('${RESULTS_FILE}'))['total'])")
  failed=$(python3 -c "import json; print(json.load(open('${RESULTS_FILE}'))['failed'])")

  echo "=== Results: ${passed}/${total} passed, ${failed} failed ==="

  if [ "$passed" = "$total" ]; then
    echo "=== ALL TESTS PASSED ==="
    break
  fi

  # Extract failed test names for focused diagnosis
  failed_tests=$(python3 -c "
import json
r = json.load(open('${RESULTS_FILE}'))
for t in r.get('tests', []):
    if t.get('outcome') in ('failed', 'error'):
        print(t.get('name', t.get('nodeid', 'unknown')))
" 2>/dev/null || echo "unknown")

  echo "=== Fixing ${failed} failures (clean context) ==="

  $CLAUDE "你是 PRD benchmark 的诊断修复专家。当前 ${passed}/${total} 测试通过，${failed} 个失败。

失败的测试：
${failed_tests}

请执行以下诊断流程：

1. 读取 ${RESULTS_FILE} 查看完整的失败详情
2. 对每个失败的测试，读取测试源码（在 ${TASK_DIR}/test_suite/ 或 ${TASK_DIR}/test_helpers/ 中）
3. 对照 ${TASK_DIR}/SCAFFOLD.yaml 和 ${TASK_DIR}/workspace/PRD.md 逐条验证测试断言是否正确
4. 如果测试与 SCAFFOLD/PRD 矛盾 → 修正测试使其严格对齐规范
5. 如果测试正确 → 读取 ${TASK_DIR}/workspace/implementation/ 中的相关代码并修复实现

关键原则：
- 绝不为了通过测试而削弱、删除、skip 任何测试
- 测试修正只允许让测试更忠于 SCAFFOLD 和 PRD，不允许让测试更宽松
- 先确保测试正确，再修复实现"

done

echo "=== Pipeline complete: ${TASK_DIR} ==="
