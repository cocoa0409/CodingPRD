"""Pre-built role headers for every role in the PRD (§2.1).

Identity rules (PRD §2.1): for `Advisor`, `Student`, and `Teacher` the
`X-User-ID` header is the `id` of the acting entity record, and ownership
checks compare resource foreign keys against it. For `DistrictAdmin` and
`WblCoordinator` the id is an opaque operator identifier.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests whose outcome does
# not depend on the caller owning a specific entity (400/404 probes, RBAC
# denials). Never use the entity-backed fallbacks for ownership-gated calls.
TEST_USERS = {
    "district_admin_headers": build_user_headers("test-district-admin-1", "DistrictAdmin"),
    "wbl_coordinator_headers": build_user_headers("test-wbl-coordinator-1", "WblCoordinator"),
    # Fallbacks for entity-backed roles — non-ownership tests only.
    "advisor_headers": build_user_headers("test-advisor-1", "Advisor"),
    "student_headers": build_user_headers("test-student-1", "Student"),
    "teacher_headers": build_user_headers("test-teacher-1", "Teacher"),
}


def make_advisor_headers(user_id: str) -> dict:
    """Advisor is entity-backed: pass the acting Advisor record's id."""
    return build_user_headers(user_id, "Advisor")


def make_student_headers(user_id: str) -> dict:
    """Student is entity-backed: pass the acting Student record's id."""
    return build_user_headers(user_id, "Student")


def make_teacher_headers(user_id: str) -> dict:
    """Teacher is entity-backed: pass the acting Teacher record's id."""
    return build_user_headers(user_id, "Teacher")
