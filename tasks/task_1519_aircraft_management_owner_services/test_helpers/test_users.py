"""Pre-built role headers for every role in the PRD (§2.1).

Shared constants are safe for the opaque operator roles and for tests that do
not exercise ownership. The Owner role is entity-backed: for ownership-gated
calls (budget approve/reject, charter trip approve/decline) the header's
X-User-ID must equal the Owner resource id — use make_owner_headers(owner_id).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Entity-backed role: shared constant is a fallback for non-ownership tests only.
    "owner_headers": build_user_headers("test-owner-1", "Owner"),
    # Opaque operator roles: shared constants are the canonical form.
    "account_executive_headers": build_user_headers("test-ae-1", "AccountExecutive"),
    "flight_ops_headers": build_user_headers("test-fo-1", "FlightOpsManager"),
    "maintenance_planner_headers": build_user_headers("test-mp-1", "MaintenancePlanner"),
    "finance_controller_headers": build_user_headers("test-fc-1", "FinanceController"),
    "compliance_officer_headers": build_user_headers("test-co-1", "ComplianceOfficer"),
    "contracts_manager_headers": build_user_headers("test-cm-1", "ContractsManager"),
    "platform_admin_headers": build_user_headers("test-pa-1", "PlatformAdmin"),
}


def make_owner_headers(user_id: str) -> dict:
    """For Owner (entity-backed by the Owner resource). Pass the actual
    Owner.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Owner")


def make_operator_headers(user_id: str, role: str) -> dict:
    """Build headers for an opaque operator role with a specific user id
    (e.g. to control prepared_by_user_id / certified_by_user_id)."""
    return build_user_headers(user_id, role)
