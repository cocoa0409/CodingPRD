"""Pre-built role headers for every role in the PRD (§2.1).

All three roles are employee-backed: X-User-ID is the id of the acting
Employee. Use the per-instance builders with the real Employee.id whenever a
call is ownership-gated (surveyor submit, primary session actions, lock owner
actions, auditor completion, coordinator activation, SoD checks).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe only for tests that do NOT exercise ownership
# (schema-400, not-found-404, or pure role-authorization rejections).
TEST_USERS = {
    "ehs_manager_headers": build_user_headers("test-ehs-manager-1", "EHSManager"),
    "ehs_auditor_headers": build_user_headers("test-ehs-auditor-1", "EHSAuditor"),
    "authorized_employee_headers": build_user_headers(
        "test-authorized-employee-1", "AuthorizedEmployee"),
}


def make_ehs_manager_headers(user_id: str) -> dict:
    """EHSManager is entity_backed:Employee — pass the acting Employee.id."""
    return build_user_headers(user_id, "EHSManager")


def make_ehs_auditor_headers(user_id: str) -> dict:
    """EHSAuditor is entity_backed:Employee — pass the acting Employee.id."""
    return build_user_headers(user_id, "EHSAuditor")


def make_authorized_employee_headers(user_id: str) -> dict:
    """AuthorizedEmployee is entity_backed:Employee — pass the acting Employee.id."""
    return build_user_headers(user_id, "AuthorizedEmployee")
