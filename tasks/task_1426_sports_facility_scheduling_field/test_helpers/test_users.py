"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership-gated calls. For the entity-backed OrgCoordinator role
# (X-User-ID is the acting Organization's id, PRD section 2.1), prefer the
# per-instance builder below whenever the call is ownership-gated.
TEST_USERS = {
    "athletics_admin_headers": build_user_headers("test-admin-1", "AthleticsAdmin"),
    "field_supervisor_headers": build_user_headers("test-supervisor-1", "FieldSupervisor"),
    "org_coordinator_headers": build_user_headers("test-coordinator-1", "OrgCoordinator"),
    "finance_clerk_headers": build_user_headers("test-clerk-1", "FinanceClerk"),
}


def make_org_coordinator_headers(user_id: str) -> dict:
    """For OrgCoordinator (entity-backed: Organization). Pass the actual
    Organization.id as user_id whenever the call is ownership-gated
    (application submit/respond/withdraw, permit confirm/cancel/reschedule)."""
    return build_user_headers(user_id, "OrgCoordinator")


def make_athletics_admin_headers(user_id: str) -> dict:
    """For AthleticsAdmin (opaque operator id). Use a specific operator id when
    the test distinguishes operators (e.g., refund-approval segregation)."""
    return build_user_headers(user_id, "AthleticsAdmin")


def make_field_supervisor_headers(user_id: str) -> dict:
    """For FieldSupervisor (opaque operator id)."""
    return build_user_headers(user_id, "FieldSupervisor")


def make_finance_clerk_headers(user_id: str) -> dict:
    """For FinanceClerk (opaque operator id). The server records it as
    initiated_by on every payment or refund row the clerk creates."""
    return build_user_headers(user_id, "FinanceClerk")
