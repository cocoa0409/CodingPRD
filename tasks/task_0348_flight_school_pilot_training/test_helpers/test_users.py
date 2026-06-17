"""Pre-built role headers for every role in the PRD.

Three roles are opaque (SchoolAdmin, Dispatcher, Mechanic): their X-User-ID is
not tied to any persisted entity, so the shared constant is the canonical form.

Two roles are entity-backed (Student -> Student.id, Instructor -> Instructor.id):
for ownership-gated calls, headers MUST be built per-instance with the actual
entity id via make_student_headers() / make_instructor_headers(). The shared
constants are fallbacks for non-ownership tests only (e.g. a 403 forbidden-role
probe, or a 401/404 probe that never reaches an ownership check).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — shared constant is canonical.
    "school_admin_headers": build_user_headers("admin-1", "SchoolAdmin"),
    "dispatcher_headers": build_user_headers("dispatcher-1", "Dispatcher"),
    "mechanic_headers": build_user_headers("mechanic-1", "Mechanic"),
    # Entity-backed roles — shared constant is a NON-ownership fallback only.
    "student_headers": build_user_headers("student-1", "Student"),
    "instructor_headers": build_user_headers("instructor-1", "Instructor"),
}


def make_school_admin_headers(user_id: str = "admin-1") -> dict:
    """SchoolAdmin (opaque). user_id is recorded but never compared."""
    return build_user_headers(user_id, "SchoolAdmin")


def make_dispatcher_headers(user_id: str = "dispatcher-1") -> dict:
    """Dispatcher (opaque). user_id is recorded but never compared."""
    return build_user_headers(user_id, "Dispatcher")


def make_mechanic_headers(user_id: str = "mechanic-1") -> dict:
    """Mechanic (opaque). user_id is recorded but never compared."""
    return build_user_headers(user_id, "Mechanic")


def make_student_headers(user_id: str) -> dict:
    """Student (entity_backed:Student). Pass the actual Student.id whenever the
    call is ownership-gated (e.g. requesting/cancelling the student's booking)."""
    return build_user_headers(user_id, "Student")


def make_instructor_headers(user_id: str) -> dict:
    """Instructor (entity_backed:Instructor). Pass the actual Instructor.id
    whenever the call is ownership-gated (flight-log post, stage checks,
    endorsement issue/revoke)."""
    return build_user_headers(user_id, "Instructor")
