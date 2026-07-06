"""Pre-built role headers for every role in the PRD (§2.1, §4).

Five roles are opaque operators (X-User-ID is an operator id, not an entity key):
SiteAdmin, CafeteriaManager, CateringCoordinator, CateringApprover, FinanceController.
The Diner role is entity_backed: X-User-ID is the acting Employee's id, so POS calls
MUST thread the real employee id via make_diner_headers(employee_id).

A CateringCoordinator is opaque, but the caller's X-User-ID is stored on a created order
as coordinator_id and later compared to the approver's X-User-ID for segregation of duties;
tests that exercise SoD control the coordinator/approver ids via the builders below.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise ownership.
TEST_USERS = {
    "site_admin_headers": build_user_headers("test-site-admin", "SiteAdmin"),
    "cafeteria_manager_headers": build_user_headers("test-cafeteria-manager", "CafeteriaManager"),
    "catering_coordinator_headers": build_user_headers("coord-1", "CateringCoordinator"),
    "catering_approver_headers": build_user_headers("appr-1", "CateringApprover"),
    "finance_controller_headers": build_user_headers("test-finance", "FinanceController"),
    # Diner shared constant is a fallback for surveys / non-ownership calls only.
    "diner_headers": build_user_headers("diner-1", "Diner"),
}


# ─── Per-instance builders ───────────────────────────────────────────────────
def make_diner_headers(user_id: str) -> dict:
    """For Diner (entity_backed:Employee). Pass the acting Employee.id as user_id when
    the call is ownership-gated (a POS transaction whose employee_id must equal X-User-ID)."""
    return build_user_headers(user_id, "Diner")


def make_coordinator_headers(user_id: str) -> dict:
    """For CateringCoordinator. The user_id is stamped on created orders as coordinator_id
    and used later for the segregation-of-duties check."""
    return build_user_headers(user_id, "CateringCoordinator")


def make_approver_headers(user_id: str) -> dict:
    """For CateringApprover. Pass an id equal to / different from the order's coordinator_id
    to exercise the segregation-of-duties precondition."""
    return build_user_headers(user_id, "CateringApprover")
