"""Pre-built role headers for every role in the PRD.

SchoolAdmin and Registrar are opaque operator identities — X-User-ID is not tied
to any persisted entity (PRD §2.1), so the shared constants are canonical for them.

Instructor and ThirdPartyExaminer are backed by Instructor records — X-User-ID is
the id of the acting Instructor entity (PRD §2.1). Ownership/conflict checks compare
the resource's instructor foreign-key to X-User-ID, so tests whose call is
ownership-gated (complete a session as its delivering instructor, grade as the named
examiner) MUST use the per-instance builders below with the real Instructor.id.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque roles — shared constant is the canonical form.
    "school_admin_headers": build_user_headers("test-school-admin-1", "SchoolAdmin"),
    "registrar_headers": build_user_headers("test-registrar-1", "Registrar"),
    # entity_backed roles — shared constants are a fallback for non-ownership tests
    # only (e.g. a 403 forbidden check that never reaches an ownership comparison).
    "instructor_headers": build_user_headers("test-instructor-1", "Instructor"),
    "examiner_headers": build_user_headers("test-examiner-1", "ThirdPartyExaminer"),
}


def make_instructor_headers(user_id: str) -> dict:
    """For Instructor (entity_backed:Instructor). Pass the actual Instructor.id as
    user_id whenever the call is ownership-gated (e.g. completing a session that
    instructor delivered)."""
    return build_user_headers(user_id, "Instructor")


def make_examiner_headers(user_id: str) -> dict:
    """For ThirdPartyExaminer (entity_backed:Instructor). Pass the actual Instructor.id
    (the examiner record) as user_id whenever the call is ownership-gated (e.g. grading
    a skills test the examiner is named on)."""
    return build_user_headers(user_id, "ThirdPartyExaminer")
