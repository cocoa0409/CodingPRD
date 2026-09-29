"""Pre-built role headers for every role named in the PRD.

Four of the seven roles are opaque: `X-User-ID` is an operator identifier that is
never compared to any row's id, so a shared constant is the canonical form.

Three roles are entity-backed (`TreatingProvider`, `Supervisor`, `Employee`):
`X-User-ID` is the id of a persisted row and ownership is enforced by comparing
that value against the addressed resource's foreign key. Every ownership-gated
call MUST therefore use the per-instance builder with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Operator identifiers used consistently across the suite.
ADMIN_USER_ID = "admin-1"
COORDINATOR_USER_ID = "coord-1"
NURSE_USER_ID = "nurse-1"
SECOND_NURSE_USER_ID = "nurse-2"
ADJUSTER_USER_ID = "adj-001"
SECOND_ADJUSTER_USER_ID = "adj-002"

TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "program_admin_headers": build_user_headers(ADMIN_USER_ID, "ProgramAdmin"),
    "rtw_coordinator_headers": build_user_headers(COORDINATOR_USER_ID, "RTWCoordinator"),
    "occ_health_nurse_headers": build_user_headers(NURSE_USER_ID, "OccHealthNurse"),
    "second_nurse_headers": build_user_headers(SECOND_NURSE_USER_ID, "OccHealthNurse"),
    "claim_adjuster_headers": build_user_headers(ADJUSTER_USER_ID, "ClaimAdjuster"),
    "second_adjuster_headers": build_user_headers(SECOND_ADJUSTER_USER_ID, "ClaimAdjuster"),
    # Entity-backed roles — these shared constants are only safe for tests that
    # do not exercise ownership (e.g. 400-on-bad-payload, unauthorized-role).
    "treating_provider_headers": build_user_headers("test-provider-1", "TreatingProvider"),
    "supervisor_headers": build_user_headers("test-supervisor-1", "Supervisor"),
    "employee_headers": build_user_headers("test-employee-1", "Employee"),
}


def make_treating_provider_headers(provider_id: str) -> dict:
    """For TreatingProvider callers. Pass the real clinician row id — ownership
    checks compare it to the addressed restriction set's treating_provider_id."""
    return build_user_headers(provider_id, "TreatingProvider")


def make_supervisor_headers(supervisor_id: str) -> dict:
    """For Supervisor callers. Pass the real supervisor row id — ownership checks
    compare it to the addressed placement's / training record's supervisor_id."""
    return build_user_headers(supervisor_id, "Supervisor")


def make_employee_headers(employee_id: str) -> dict:
    """For Employee callers. Pass the real worker row id — ownership checks compare
    it to the employee_id of the addressed claim or of the claim owning the
    addressed placement."""
    return build_user_headers(employee_id, "Employee")


def make_adjuster_headers(user_id: str) -> dict:
    """For ClaimAdjuster callers. The claim's adjuster_user_id is load-bearing:
    only that same X-User-ID may decide the claim's placement funding."""
    return build_user_headers(user_id, "ClaimAdjuster")


def make_coordinator_headers(user_id: str) -> dict:
    """For RTWCoordinator callers whose operator identity matters (the placement's
    created_by_user_id drives the segregation-of-duties bar)."""
    return build_user_headers(user_id, "RTWCoordinator")


def make_nurse_headers(user_id: str) -> dict:
    """For OccHealthNurse callers whose operator identity matters (a member who
    cast a counted ballot may not close the panel)."""
    return build_user_headers(user_id, "OccHealthNurse")
