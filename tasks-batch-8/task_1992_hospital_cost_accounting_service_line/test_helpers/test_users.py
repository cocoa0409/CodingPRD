"""Pre-built role headers for every role in the PRD (§2.1).

All three roles are opaque (PRD §2.1: X-User-ID is never compared to any
resource id), so shared constants are the canonical form for every role.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "cost_analyst_headers": build_user_headers("test-analyst-1", "CostAnalyst"),
    "finance_controller_headers": build_user_headers("test-controller-1", "FinanceController"),
    "service_line_manager_headers": build_user_headers("test-manager-1", "ServiceLineManager"),
}
