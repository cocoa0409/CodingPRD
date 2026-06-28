"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (Registrar, Anonymous) and for tests
# that do not exercise ownership (400-on-bad-payload, 404-on-missing-resource).
TEST_USERS = {
    # opaque roles: the shared constant is the canonical form.
    "registrar_headers": build_user_headers("registrar-op-1", "Registrar"),
    "anonymous_headers": build_user_headers("anon-public-1", "Anonymous"),
    # entity_backed roles: shared constant is a fallback for NON-ownership tests only
    # (e.g. asserting a 403 for an unauthorized role on a missing/other resource).
    "student_headers": build_user_headers("test-student-1", "Student"),
    "instructor_headers": build_user_headers("test-instructor-1", "Instructor"),
}


# Per-instance builders — required for every entity_backed role.
def make_student_headers(user_id: str) -> dict:
    """For Student (entity_backed:Student). Pass the actual Student.id as user_id
    whenever the call is ownership-gated (acting on the student's own enrollment,
    practice attempt, installment plan, or guarantee claim)."""
    return build_user_headers(user_id, "Student")


def make_instructor_headers(user_id: str) -> dict:
    """For Instructor (entity_backed:Instructor). Pass the actual Instructor.id as
    user_id for instructor actions (attendance, scoring, voiding)."""
    return build_user_headers(user_id, "Instructor")


def make_registrar_headers(user_id: str = "registrar-op-1") -> dict:
    """For Registrar (opaque). X-User-ID is an operator id not tied to any entity."""
    return build_user_headers(user_id, "Registrar")


def make_anonymous_headers(user_id: str = "anon-public-1") -> dict:
    """For Anonymous (opaque). X-User-ID is an opaque public identifier."""
    return build_user_headers(user_id, "Anonymous")
