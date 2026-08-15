"""Pre-built role headers for every role in the PRD (§2.1).

LanguageAccessCoordinator and ComplianceOfficer are opaque identities:
X-User-ID is not tied to any persisted entity. DepartmentLiaison is
entity-backed by Department (X-User-ID is the department's id); Interpreter
and QualityReviewer are entity-backed by Interpreter. Ownership-gated calls
MUST use the per-instance builders with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "coordinator_headers": build_user_headers("test-coordinator-1", "LanguageAccessCoordinator"),
    "officer_headers": build_user_headers("test-officer-1", "ComplianceOfficer"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "liaison_headers": build_user_headers("test-liaison-1", "DepartmentLiaison"),
    "interpreter_headers": build_user_headers("test-interpreter-1", "Interpreter"),
    "reviewer_headers": build_user_headers("test-reviewer-1", "QualityReviewer"),
}


def make_coordinator_headers(user_id: str = "test-coordinator-1") -> dict:
    return build_user_headers(user_id, "LanguageAccessCoordinator")


def make_officer_headers(user_id: str = "test-officer-1") -> dict:
    """ComplianceOfficer is opaque; pass a distinct user_id per officer when a
    test exercises intake/adjudication segregation of duties."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_liaison_headers(department_id: str) -> dict:
    """For DepartmentLiaison (entity_backed:Department). Pass the acting
    Department.id whenever the call is ownership-gated."""
    return build_user_headers(department_id, "DepartmentLiaison")


def make_interpreter_headers(interpreter_id: str) -> dict:
    """For Interpreter (entity_backed:Interpreter). Pass the acting
    Interpreter.id whenever the call is ownership-gated."""
    return build_user_headers(interpreter_id, "Interpreter")


def make_reviewer_headers(interpreter_id: str) -> dict:
    """For QualityReviewer (entity_backed:Interpreter). Pass the acting
    Interpreter.id whenever the call is ownership-gated."""
    return build_user_headers(interpreter_id, "QualityReviewer")
