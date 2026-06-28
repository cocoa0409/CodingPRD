"""Pre-built role headers for every role in the PRD (§2.1).

Registrar, DSO, Instructor, Anonymous are opaque roles: X-User-ID is an
arbitrary operator identifier not compared against any entity.

Student (entity_backed:Student) and CorporateSponsor (entity_backed:CorporateContract)
are ownership-bound: X-User-ID MUST be the id of the owned entity for any
ownership-gated call. Use the per-instance builders below in those cases.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for ownership-independent tests.
TEST_USERS = {
    "registrar_headers": build_user_headers("test-registrar-1", "Registrar"),
    "dso_headers": build_user_headers("test-dso-1", "DSO"),
    "instructor_headers": build_user_headers("test-instructor-1", "Instructor"),
    # Fallback constants for entity_backed roles — only valid for non-ownership tests.
    "student_headers": build_user_headers("test-student-1", "Student"),
    "corporate_sponsor_headers": build_user_headers("test-sponsor-1", "CorporateSponsor"),
}


# ---- Per-instance builders for entity_backed roles ----
def make_student_headers(student_id: str) -> dict:
    """For Student (entity_backed:Student). Pass the actual Student.id whenever
    the call is ownership-gated (own add-on cancel, own placement-test, etc.)."""
    return build_user_headers(student_id, "Student")


def make_corporate_sponsor_headers(contract_id: str) -> dict:
    """For CorporateSponsor (entity_backed:CorporateContract). Pass the actual
    CorporateContract.id whenever the call is ownership-gated."""
    return build_user_headers(contract_id, "CorporateSponsor")
