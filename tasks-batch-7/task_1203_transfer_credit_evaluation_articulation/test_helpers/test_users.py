"""Pre-built role headers for every role in the PRD.

The Student role is entity-backed by TransferStudent: ownership-gated calls
MUST use make_student_headers(student["id"]) with the real student id. The
shared constant is a fallback only for tests that do not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are canonical.
    "admin_headers": build_user_headers("test-admin-1", "RegistrarAdmin"),
    "staff_headers": build_user_headers("test-staff-1", "TransferCenterStaff"),
    "evaluator_headers": build_user_headers("test-evaluator-1", "TransferEvaluator"),
    "faculty_headers": build_user_headers("test-faculty-1", "FacultyAdjudicator"),
    # Entity-backed role: shared constant is a fallback for non-ownership tests only.
    "student_headers": build_user_headers("test-student-1", "Student"),
}


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RegistrarAdmin")


def make_staff_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TransferCenterStaff")


def make_evaluator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "TransferEvaluator")


def make_faculty_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FacultyAdjudicator")


def make_student_headers(user_id: str) -> dict:
    """For the entity-backed Student role. Pass the actual TransferStudent.id
    whenever the call is ownership-gated (petitions, appeals, PLA submission,
    own-record reads)."""
    return build_user_headers(user_id, "Student")
