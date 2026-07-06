"""Pre-built role headers for every role in the Foundation Repair PRD (§2.1).

Five roles carry an opaque identity — SalesAgent, FieldEngineer, OpsCoordinator,
ClaimsAdjuster, Admin — whose X-User-ID is never compared to any persisted entity.
The Customer role is entity-backed: its X-User-ID must equal the id of the acting Lead,
and ownership is enforced on every customer-scoped mutation. Ownership-gated customer calls
MUST therefore use make_customer_headers(lead_id) with the real Lead id — never the shared
constant (which is not any Lead's id and would fail every ownership check).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the five opaque roles, and for customer tests that do NOT
# exercise ownership (e.g. a role-denied 403 that is decided before ownership).
TEST_USERS = {
    "sales_agent_headers": build_user_headers("test-sales-1", "SalesAgent"),
    "field_engineer_headers": build_user_headers("test-engineer-1", "FieldEngineer"),
    "ops_coordinator_headers": build_user_headers("test-ops-1", "OpsCoordinator"),
    "claims_adjuster_headers": build_user_headers("test-adjuster-1", "ClaimsAdjuster"),
    "admin_headers": build_user_headers("test-admin-1", "Admin"),
    # Customer shared constant: only for non-ownership-gated scenarios.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For the Customer role (entity_backed:Lead). Pass the acting Lead's id as user_id
    for every ownership-gated call (accept/reject quote, file/resubmit claim, transfer
    warranty) so the §2.1 ownership check passes."""
    return build_user_headers(user_id, "Customer")


def make_sales_agent_headers(user_id: str = "test-sales-1") -> dict:
    return build_user_headers(user_id, "SalesAgent")


def make_field_engineer_headers(user_id: str = "test-engineer-1") -> dict:
    return build_user_headers(user_id, "FieldEngineer")


def make_ops_coordinator_headers(user_id: str = "test-ops-1") -> dict:
    return build_user_headers(user_id, "OpsCoordinator")


def make_claims_adjuster_headers(user_id: str = "test-adjuster-1") -> dict:
    return build_user_headers(user_id, "ClaimsAdjuster")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "Admin")
