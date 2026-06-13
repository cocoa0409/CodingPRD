"""Pre-built role headers for every role in the PRD (§2.1).

All four roles are opaque operator identities: per PRD §2.1, X-User-ID is never
compared to any persisted entity's id, so shared constants are the canonical form
for every role and no per-instance ownership builders are required.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "shop_manager_headers": build_user_headers("test-shop-manager-1", "ShopManager"),
    "bridal_consultant_headers": build_user_headers("test-bridal-consultant-1", "BridalConsultant"),
    "seamstress_headers": build_user_headers("test-seamstress-1", "Seamstress"),
    "finance_clerk_headers": build_user_headers("test-finance-clerk-1", "FinanceClerk"),
}
