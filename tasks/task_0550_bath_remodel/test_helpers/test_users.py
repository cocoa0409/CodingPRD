"""Pre-built role headers for every role in the PRD.

Customer and Designer are entity-backed: ownership is enforced against a
persisted record, so ownership-gated calls MUST use the per-instance builders
(make_customer_headers / make_designer_headers) with the real entity id.
FinanceOfficer, InstallCoordinator, and PlatformAdmin are opaque operator
identities authorized purely by role.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for entity-backed roles only in
# tests that do NOT exercise ownership (e.g. 400/403/404 before the ownership check).
TEST_USERS = {
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "designer_headers": build_user_headers("test-designer-1", "Designer"),
    "finance_officer_headers": build_user_headers("test-finance-1", "FinanceOfficer"),
    "install_coordinator_headers": build_user_headers("test-coordinator-1", "InstallCoordinator"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the acting Customer.id whenever
    the call is ownership-gated (accept, request-revision, warranty claim, own cancel)."""
    return build_user_headers(user_id, "Customer")


def make_designer_headers(user_id: str) -> dict:
    """For Designer (entity_backed:Designer). Pass the assigned Designer.id whenever
    the call is ownership-gated (complete appointment, create/present quote)."""
    return build_user_headers(user_id, "Designer")
