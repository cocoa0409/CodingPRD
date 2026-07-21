"""Pre-built role headers for every role in the Down-Payment Assistance API.

Only the Applicant role is entity-backed: when acting as an Applicant, the
X-User-ID must equal the acting applicant's own id (PRD Section 2.1). Every
ownership-gated applicant call MUST therefore use make_applicant_headers(id).
The other five roles carry opaque operator identifiers.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# applicant ownership (404-on-missing, 400-on-bad-payload, opaque-role calls).
TEST_USERS = {
    "program_admin_headers": build_user_headers("test-program-admin-1", "ProgramAdmin"),
    "case_manager_headers": build_user_headers("test-case-manager-1", "CaseManager"),
    "closing_coordinator_headers": build_user_headers("test-closing-coordinator-1", "ClosingCoordinator"),
    "servicer_headers": build_user_headers("test-servicer-1", "Servicer"),
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    # Fallback applicant constant — only for non-ownership scenarios.
    "applicant_headers": build_user_headers("test-applicant-1", "Applicant"),
}


# --- Per-instance builders --------------------------------------------------
def make_applicant_headers(user_id: str) -> dict:
    """For the Applicant role (entity_backed:Applicant). Pass the actual
    Applicant.id as user_id on every ownership-gated call (submit, resubmit,
    withdraw, enroll, cancel-enrollment)."""
    return build_user_headers(user_id, "Applicant")


def make_case_manager_headers(user_id: str) -> dict:
    """For CaseManager (opaque). Use a distinct user_id to drive/observe the
    separation-of-duties audit trail (reviewer vs approver identities)."""
    return build_user_headers(user_id, "CaseManager")


def make_program_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProgramAdmin")


def make_closing_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClosingCoordinator")


def make_servicer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Servicer")
