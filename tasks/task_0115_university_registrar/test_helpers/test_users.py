"""Pre-built role headers for every role in the University Registrar PRD.

Per PRD §2.1:
  - When X-User-Role is Student, X-User-ID is the id of the acting Student;
    ownership checks compare the resource's student_id to X-User-ID. Student is
    therefore entity-backed: ownership-gated calls MUST use make_student_headers
    with the real Student.id.
  - When X-User-Role is Advisor, Registrar, or Bursar, X-User-ID is an opaque
    operator identifier not tied to any persisted entity; a shared constant is
    the canonical form for those roles.
"""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — canonical for the opaque operator roles, and a safe
# fallback for Student only on calls that do NOT exercise ownership
# (e.g. 401/403/404 paths that fail before the ownership check, or reads).
TEST_USERS = {
    "registrar_headers": build_user_headers("op-registrar-1", "Registrar"),
    "advisor_headers": build_user_headers("op-advisor-1", "Advisor"),
    "bursar_headers": build_user_headers("op-bursar-1", "Bursar"),
    # Student shared constant: an arbitrary id that equals no real Student.id.
    # Only valid for non-ownership tests.
    "student_headers": build_user_headers("op-student-anon", "Student"),
}


def make_student_headers(user_id: str) -> dict:
    """For the Student role (entity_backed:Student). Pass the actual Student.id
    as user_id whenever the call is ownership-gated (POST /enrollments,
    /enrollments/{id}/drop, /enrollments/{id}/withdraw, /swap-requests)."""
    return build_user_headers(user_id, "Student")


def make_registrar_headers(user_id: str = "op-registrar-1") -> dict:
    return build_user_headers(user_id, "Registrar")


def make_advisor_headers(user_id: str = "op-advisor-1") -> dict:
    return build_user_headers(user_id, "Advisor")


def make_bursar_headers(user_id: str = "op-bursar-1") -> dict:
    return build_user_headers(user_id, "Bursar")
