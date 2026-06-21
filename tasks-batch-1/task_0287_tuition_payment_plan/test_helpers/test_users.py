"""Pre-built role headers for every role in the PRD.

Registrar and Bursar are opaque operator roles: X-User-ID is recorded but never
compared to an entity id, so a shared constant is the canonical form. Student is
entity-backed: X-User-ID must equal the acting Student's id for ownership checks,
so use make_student_headers(student_id) whenever a Student call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Registrar/Bursar are opaque, so these are canonical for them.
# The student constant is a fallback for non-ownership tests only (e.g. 403/404).
TEST_USERS = {
    "registrar_headers": build_user_headers("registrar-op-1", "Registrar"),
    "bursar_headers": build_user_headers("bursar-op-1", "Bursar"),
    "student_headers": build_user_headers("student-fallback-1", "Student"),
}


def make_registrar_headers(user_id: str = "registrar-op-1") -> dict:
    """Registrar is opaque; user_id need not match any entity."""
    return build_user_headers(user_id, "Registrar")


def make_bursar_headers(user_id: str = "bursar-op-1") -> dict:
    """Bursar is opaque; user_id need not match any entity."""
    return build_user_headers(user_id, "Bursar")


def make_student_headers(student_id: str) -> dict:
    """For Student (entity_backed:Student). Pass the actual Student.id as student_id
    whenever the call is ownership-gated (payment create/settle on own enrollment)."""
    return build_user_headers(student_id, "Student")
