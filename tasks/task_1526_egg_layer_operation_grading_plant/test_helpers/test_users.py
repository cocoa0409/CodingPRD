"""Pre-built role headers for the six roles of the PRD (§2.1).

All roles are opaque: X-User-ID is an operator identifier never compared to
entity ids. The only place user identity matters is the pair of
segregation-of-duties checks, which compare X-User-ID strings stored on the
resource (grading-run submitted_by vs confirmer; test collected_by vs result
recorder). Use make_role_headers() with a shared user id to exercise those.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    "farm_manager_headers": build_user_headers("fm-1", "FarmManager"),
    "quality_grader_headers": build_user_headers("grader-1", "QualityGrader"),
    "qa_manager_headers": build_user_headers("qa-1", "QAManager"),
    "contract_manager_headers": build_user_headers("cm-1", "ContractManager"),
    "compliance_officer_headers": build_user_headers("co-1", "ComplianceOfficer"),
}


def make_role_headers(role: str, user_id: str) -> dict:
    """Build headers for an arbitrary operator id acting in the given role.

    Used by segregation-of-duties tests where the same operator id must act
    under two different roles across a paired workflow.
    """
    return build_user_headers(user_id, role)
