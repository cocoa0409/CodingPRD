"""Pre-built role headers for every role in the PRD (§2.1).

Student is entity_backed: its X-User-ID must be the id of the acting Student
record for any ownership-gated call — use make_student_headers(student_id) in
that case. The shared TEST_USERS entry for Student is only a fallback for
tests that do not exercise ownership (none should).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants for the opaque (non-entity-backed) staff roles. These user
# ids are never compared to any entity id (PRD §2.1).
COORD_A_HEADERS = build_user_headers("coord-a", "ProgramCoordinator")
COORD_B_HEADERS = build_user_headers("coord-b", "ProgramCoordinator")
FACULTY_HEADERS = build_user_headers("fac-1", "FacultyApprover")
SAFETY_HEADERS = build_user_headers("safety-1", "SafetyOfficer")
BURSAR_HEADERS = build_user_headers("bursar-1", "BursarOffice")

TEST_USERS = {
    "student_headers": build_user_headers("test-student-1", "Student"),
    "coordinator_headers": COORD_A_HEADERS,
    "coordinator_b_headers": COORD_B_HEADERS,
    "faculty_headers": FACULTY_HEADERS,
    "safety_headers": SAFETY_HEADERS,
    "bursar_headers": BURSAR_HEADERS,
}


def make_student_headers(user_id: str) -> dict:
    """Student is entity_backed:Student — pass the actual Student.id whenever
    the call is ownership-gated (application actions, pre-approvals, insurance,
    incidents, own record reads)."""
    return build_user_headers(user_id, "Student")


def make_coordinator_headers(user_id: str) -> dict:
    """ProgramCoordinator (opaque). Distinct user ids matter for the
    segregation-of-duties rule on approval."""
    return build_user_headers(user_id, "ProgramCoordinator")


def make_faculty_headers(user_id: str) -> dict:
    """FacultyApprover (opaque)."""
    return build_user_headers(user_id, "FacultyApprover")


def make_safety_headers(user_id: str) -> dict:
    """SafetyOfficer (opaque)."""
    return build_user_headers(user_id, "SafetyOfficer")


def make_bursar_headers(user_id: str) -> dict:
    """BursarOffice (opaque)."""
    return build_user_headers(user_id, "BursarOffice")
