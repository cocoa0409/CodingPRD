"""Pre-built role headers for every role in PRD §2.1.

All four roles have opaque identity (PRD §2.1): X-User-ID is an opaque operator
identifier, never compared against any entity id — except the segregation-of-duties
check on correction approval, which compares against the recorded proposer_user_id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("platform-admin-1", "PlatformAdmin"),
    "plan_admin_headers": build_user_headers("plan-admin-1", "PlanAdministrator"),
    "analyst_headers": build_user_headers("analyst-1", "ComplianceAnalyst"),
    "auditor_headers": build_user_headers("auditor-1", "Auditor"),
}


def make_platform_admin_headers(user_id: str) -> dict:
    """PlatformAdmin headers with a specific opaque operator id (e.g. clock driving)."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_plan_admin_headers(user_id: str) -> dict:
    """PlanAdministrator headers with a specific opaque operator id.

    Required for the segregation-of-duties path: the approver's X-User-ID must
    differ from the proposer_user_id recorded at correction proposal time.
    """
    return build_user_headers(user_id, "PlanAdministrator")


def make_analyst_headers(user_id: str) -> dict:
    """ComplianceAnalyst headers with a specific opaque operator id.

    The proposer's X-User-ID is recorded as proposer_user_id at proposal time.
    """
    return build_user_headers(user_id, "ComplianceAnalyst")


def make_auditor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Auditor")
