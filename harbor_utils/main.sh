#!/usr/bin/env bash
# =============================================================================
#  Harbor 一键流水线
# =============================================================================
#
#  作用
#  ----
#  把 tasks/task_*/ 全量 hydrate 到 harbor_tasks/，再把 harbor_tasks/ 下所有
#  hydrated 任务打成一个 Harbor 数据集。等价于：
#
#      bash harbor_utils/prepare-all.sh
#      bash harbor_utils/pack-dataset.sh "$@"
#
#  用法
#  ----
#      bash harbor_utils/main.sh
#      bash harbor_utils/main.sh -n my-org/my-bench -d "subset desc"
#
#  传给 main.sh 的所有参数会原样转给 pack-dataset.sh（prepare-all.sh 不吃参数）。
# =============================================================================

set -euo pipefail

LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ">>> step 1/2: hydrating tasks (prepare-all.sh)"
bash "$LIB_DIR/prepare-all.sh"

echo
echo ">>> step 2/2: packing dataset (pack-dataset.sh)"
bash "$LIB_DIR/pack-dataset.sh" "$@"
