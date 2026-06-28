"""Pre-built role headers for every role in the PRD (§2.1).

Two roles are opaque (Registrar, FinancialAidOfficer): their X-User-ID is an
operator identifier never compared to an entity id, so a shared constant is the
canonical form. Two roles are entity_backed (Instructor -> Instructor.id,
Student -> Student.id): for ownership-gated calls the per-instance builder must
be used with the actual entity id, never the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constant is canonical.
    "registrar_headers": build_user_headers("op-registrar-1", "Registrar"),
    "financial_aid_officer_headers": build_user_headers("op-fao-1", "FinancialAidOfficer"),
    # Entity_backed roles — shared constant is a fallback for non-ownership tests
    # (e.g. 422-on-bad-payload, 404-on-missing-resource, FORBIDDEN_ROLE checks).
    "instructor_headers": build_user_headers("test-instructor-1", "Instructor"),
    "student_headers": build_user_headers("test-student-1", "Student"),
}


def make_registrar_headers(user_id: str = "op-registrar-1") -> dict:
    """Registrar is opaque; user_id is never compared to an entity id."""
    return build_user_headers(user_id, "Registrar")


def make_financial_aid_officer_headers(user_id: str = "op-fao-1") -> dict:
    """FinancialAidOfficer is opaque; user_id is never compared to an entity id."""
    return build_user_headers(user_id, "FinancialAidOfficer")


def make_instructor_headers(user_id: str) -> dict:
    """For Instructor (entity_backed:Instructor). Pass the actual Instructor.id
    whenever the call is ownership/identity-gated."""
    return build_user_headers(user_id, "Instructor")


def make_student_headers(user_id: str) -> dict:
    """For Student (entity_backed:Student). Pass the actual Student.id whenever
    the call is ownership-gated (exam-application actions compare it to the
    enrollment's student_id)."""
    return build_user_headers(user_id, "Student")
