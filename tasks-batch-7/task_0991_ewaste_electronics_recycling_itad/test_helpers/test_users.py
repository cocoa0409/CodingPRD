"""Pre-built role headers for every role in the PRD (§2.1).

AccountManager is entity-backed: its X-User-ID must be the acting
BusinessAccount's id, so any ownership-gated call MUST use
make_account_manager_headers(account["id"]) rather than the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: the shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "compliance_officer_headers": build_user_headers("test-co-1", "ComplianceOfficer"),
    "intake_operator_headers": build_user_headers("test-intake-1", "IntakeOperator"),
    "destruction_technician_headers": build_user_headers("test-tech-1", "DestructionTechnician"),
    "logistics_coordinator_headers": build_user_headers("test-logistics-1", "LogisticsCoordinator"),
    # Entity-backed role: shared constant is a fallback for non-ownership tests only.
    "account_manager_headers": build_user_headers("test-am-1", "AccountManager"),
}


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_compliance_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ComplianceOfficer")


def make_account_manager_headers(user_id: str) -> dict:
    """For AccountManager (entity-backed by BusinessAccount). Pass the actual
    account id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "AccountManager")


def make_intake_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "IntakeOperator")


def make_destruction_technician_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "DestructionTechnician")


def make_logistics_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LogisticsCoordinator")
