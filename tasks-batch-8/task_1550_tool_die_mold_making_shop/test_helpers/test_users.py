"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles (ShopAdmin, Estimator, ToolingEngineer, ProjectManager,
QualityManager, FinanceAdmin) never have X-User-ID compared against an entity
id, so shared constants are safe. The Customer role is entity-backed: any
ownership-gated call MUST use make_customer_headers(customer_id) with the
actual customer record id.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import FINANCE_ISSUER_USER_ID, FINANCE_PAYER_USER_ID

TEST_USERS = {
    "shop_admin_headers": build_user_headers("shop-admin-1", "ShopAdmin"),
    "estimator_headers": build_user_headers("estimator-1", "Estimator"),
    "tooling_engineer_headers": build_user_headers("tooling-engineer-1", "ToolingEngineer"),
    "project_manager_headers": build_user_headers("project-manager-1", "ProjectManager"),
    "quality_manager_headers": build_user_headers("quality-manager-1", "QualityManager"),
    # Two distinct FinanceAdmin identities keep invoice issuance and payment
    # recording segregation-of-duties clean in composite fixtures.
    "finance_issuer_headers": build_user_headers(FINANCE_ISSUER_USER_ID, "FinanceAdmin"),
    "finance_payer_headers": build_user_headers(FINANCE_PAYER_USER_ID, "FinanceAdmin"),
    # Fallback Customer identity — only for calls that are NOT ownership-gated.
    "customer_headers": build_user_headers("customer-anon-1", "Customer"),
}


def make_customer_headers(customer_id: str) -> dict:
    """Customer is entity-backed: X-User-ID must be the Customer record's id
    for any ownership-gated call (design submit, quote respond, ECO filing and
    customer decisions, seq-5 milestone, shot reports, warranty claims)."""
    return build_user_headers(customer_id, "Customer")
