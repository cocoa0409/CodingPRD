"""Pre-built role headers for every role in the PRD (PRD §2.1).

Six of the seven roles are opaque operator identities: `X-User-ID` is an opaque
operator identifier that is not tied to any persisted entity.  The `Student`
role is the exception — `X-User-ID` is the `id` of the acting student record —
so every ownership-gated Student call MUST use ``make_student_headers()`` with
a real Student `id`.
"""
from prd_bench_local_runner.testing import build_user_headers

# Fixed operator identifiers used throughout the suite.  Distinct suffixes let
# tests exercise the actor-binding and segregation-of-duties rules.
ADMIN_1 = "admin-1"
DIRECTOR_1 = "director-1"
DIRECTOR_2 = "director-2"
STAFF_1 = "staff-1"
STAFF_2 = "staff-2"
PROCTOR_1 = "proctor-1"
PROCTOR_2 = "proctor-2"
INSTRUCTOR_1 = "instructor-1"
INSTRUCTOR_2 = "instructor-2"
REGISTRAR_1 = "registrar-1"
REGISTRAR_2 = "registrar-2"
DUAL_HAT_1 = "dual-hat-1"


TEST_USERS = {
    # Opaque roles — the shared constant is the canonical form.
    "system_admin_headers": build_user_headers(ADMIN_1, "SystemAdmin"),
    "assessment_director_headers": build_user_headers(DIRECTOR_1, "AssessmentDirector"),
    "assessment_staff_headers": build_user_headers(STAFF_1, "AssessmentStaff"),
    "proctor_headers": build_user_headers(PROCTOR_1, "Proctor"),
    "instructor_headers": build_user_headers(INSTRUCTOR_1, "Instructor"),
    "registrar_headers": build_user_headers(REGISTRAR_1, "Registrar"),
    # Student is entity_backed: this shared constant is a fallback for tests
    # that do not depend on the caller owning the subject resource.
    "student_headers": build_user_headers("test-student-1", "Student"),
}


def make_system_admin_headers(user_id: str = ADMIN_1) -> dict:
    """Headers for a `SystemAdmin` acting under an opaque operator identifier."""
    return build_user_headers(user_id, "SystemAdmin")


def make_assessment_director_headers(user_id: str = DIRECTOR_1) -> dict:
    """Headers for an `AssessmentDirector` acting under an opaque identifier."""
    return build_user_headers(user_id, "AssessmentDirector")


def make_assessment_staff_headers(user_id: str = STAFF_1) -> dict:
    """Headers for an `AssessmentStaff` operator acting under an opaque id."""
    return build_user_headers(user_id, "AssessmentStaff")


def make_proctor_headers(user_id: str = PROCTOR_1) -> dict:
    """Headers for a `Proctor`.  Pass the session's `proctor_user_id` whenever
    the call is bound to the assigned proctor."""
    return build_user_headers(user_id, "Proctor")


def make_instructor_headers(user_id: str = INSTRUCTOR_1) -> dict:
    """Headers for an `Instructor`.  Pass the override's `issued_by_user_id`
    whenever the call is bound to the issuing instructor."""
    return build_user_headers(user_id, "Instructor")


def make_registrar_headers(user_id: str = REGISTRAR_1) -> dict:
    """Headers for a `Registrar`.  Pass the appeal's `reviewed_by_user_id`
    whenever the call is bound to the owning reviewer."""
    return build_user_headers(user_id, "Registrar")


def make_student_headers(student_id: str) -> dict:
    """Headers for the `Student` role.

    `X-User-ID` is the `id` of the acting student record, so this builder MUST
    be called with the real Student `id` for every ownership-gated call.
    """
    return build_user_headers(student_id, "Student")
