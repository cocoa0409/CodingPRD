"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the six opaque roles, whose X-User-ID is not
# compared against any persisted entity (PRD §2.1). The CoveredEmployee entry
# is a fallback for tests that do not exercise ownership; ownership-gated
# calls MUST use make_covered_employee_headers(<employee id>) instead.
TEST_USERS = {
    "ops_admin_headers": build_user_headers("ops-admin-1", "OpsAdmin"),
    "compliance_admin_headers": build_user_headers("ca-1", "ComplianceAdmin"),
    "surveillance_analyst_headers": build_user_headers("sa-1", "SurveillanceAnalyst"),
    "filing_officer_headers": build_user_headers("fo-1", "FilingOfficer"),
    "covered_employee_headers": build_user_headers("test-employee-1", "CoveredEmployee"),
}


def make_covered_employee_headers(user_id: str) -> dict:
    """CoveredEmployee identity is the Employee id itself (PRD §2.1); pass the
    actual employee's id for every ownership-gated call."""
    return build_user_headers(user_id, "CoveredEmployee")


def make_best_ex_analyst_headers(user_id: str) -> dict:
    """BestExAnalyst identity is opaque but recorded as created_by_user_id on
    reviews (PRD §3.5); use a stable id when segregation-of-duties matters."""
    return build_user_headers(user_id, "BestExAnalyst")


def make_committee_member_headers(user_id: str) -> dict:
    """CommitteeMember identity is opaque but recorded in voter_user_ids
    (PRD §3.5); use a distinct id per voter."""
    return build_user_headers(user_id, "CommitteeMember")
