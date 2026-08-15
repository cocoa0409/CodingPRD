"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# Customer ownership gating.
TEST_USERS = {
    # entity_backed role (Customer): fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    # opaque roles: shared constants are the canonical form.
    "sales_rep_headers": build_user_headers("test-sales-rep-1", "SalesRep"),
    "crating_designer_headers": build_user_headers("test-designer-1", "CratingDesigner"),
    "shop_foreman_headers": build_user_headers("test-foreman-1", "ShopForeman"),
    "compliance_officer_headers": build_user_headers("test-officer-1", "ComplianceOfficer"),
    "logistics_coordinator_headers": build_user_headers("test-logistics-1", "LogisticsCoordinator"),
    "claims_adjuster_headers": build_user_headers("test-adjuster-1", "ClaimsAdjuster"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated (accept-quote, claims, appeal)."""
    return build_user_headers(user_id, "Customer")


def make_sales_rep_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SalesRep")


def make_crating_designer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CratingDesigner")


def make_shop_foreman_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ShopForeman")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_logistics_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LogisticsCoordinator")


def make_claims_adjuster_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
