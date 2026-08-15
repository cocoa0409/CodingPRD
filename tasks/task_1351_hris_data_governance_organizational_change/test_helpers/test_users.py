"""Pre-built role headers for every role in the PRD.

All five roles are opaque (X-User-ID is not tied to any persisted entity id),
so shared constants are canonical. The per-instance builders below exist so
tests can thread a specific operator id through calls whose outcomes depend on
identity (created_by / approver_1_id comparisons, grant user_id matching).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "analyst_headers": build_user_headers("analyst-1", "HrisAnalyst"),
    "steward_headers": build_user_headers("steward-1", "DataSteward"),
    "approver_headers": build_user_headers("appr-1", "ChangeApprover"),
    "operator_headers": build_user_headers("operator-1", "IntegrationOperator"),
    "security_admin_headers": build_user_headers("secadmin-1", "SecurityAdmin"),
}


def make_analyst_headers(user_id: str) -> dict:
    """HrisAnalyst acting as a specific operator id (e.g. created_by anchor)."""
    return build_user_headers(user_id, "HrisAnalyst")


def make_steward_headers(user_id: str) -> dict:
    """DataSteward acting as a specific operator id."""
    return build_user_headers(user_id, "DataSteward")


def make_approver_headers(user_id: str) -> dict:
    """ChangeApprover acting as a specific operator id (must match a grant's user_id)."""
    return build_user_headers(user_id, "ChangeApprover")


def make_operator_headers(user_id: str) -> dict:
    """IntegrationOperator acting as a specific operator id."""
    return build_user_headers(user_id, "IntegrationOperator")


def make_security_admin_headers(user_id: str) -> dict:
    """SecurityAdmin acting as a specific operator id (grant approve/revoke identity)."""
    return build_user_headers(user_id, "SecurityAdmin")
