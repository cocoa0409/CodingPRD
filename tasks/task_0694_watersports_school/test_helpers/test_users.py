"""Pre-built role headers for every role in the PRD (§2.1).

SchoolAdmin is an opaque operator identity that the server never compares to a
persisted entity id, so its shared constant is the canonical form. Instructor
and Student are entity-backed: their X-User-ID must equal a real Instructor.id
or Student.id for ownership-gated calls, so every ownership-gated call MUST use
the per-instance builder with the actual entity id.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants.
# - admin: opaque, canonical form, safe everywhere SchoolAdmin is permitted.
# - instructor/student: fallback for NON-ownership tests only
#   (e.g. 401/403/404/400 negative cases). Ownership-gated calls MUST instead
#   use make_instructor_headers(id) / make_student_headers(id).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "SchoolAdmin"),
    "instructor_headers": build_user_headers("test-instructor-1", "Instructor"),
    "student_headers": build_user_headers("test-student-1", "Student"),
    # An unknown / unrecognized role for the ERR_UNAUTHENTICATED path.
    "unknown_role_headers": build_user_headers("test-ghost-1", "Ghost"),
}


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """SchoolAdmin (opaque). user_id is never compared to any entity id."""
    return build_user_headers(user_id, "SchoolAdmin")


def make_instructor_headers(user_id: str) -> dict:
    """For the Instructor role (entity_backed:Instructor). Pass the actual
    Instructor.id whenever the call is ownership-gated (start / complete /
    check-in on a session whose instructor_id equals this id)."""
    return build_user_headers(user_id, "Instructor")


def make_student_headers(user_id: str) -> dict:
    """For the Student role (entity_backed:Student). Pass the actual Student.id
    whenever the call is ownership-gated (acting on own enrollments, bookings,
    rentals, waivers, memberships)."""
    return build_user_headers(user_id, "Student")
