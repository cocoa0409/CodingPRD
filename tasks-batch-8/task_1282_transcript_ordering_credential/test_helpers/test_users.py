"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for Student only in tests whose
# success does NOT depend on the caller owning the subject resource.
TEST_USERS = {
    # entity_backed:Student — fallback for non-ownership tests only
    "student_headers": build_user_headers("test-student-1", "Student"),
    # opaque roles — canonical form
    "operator_headers": build_user_headers("test-operator-1", "RegistrarOperator"),
    "reviewer_headers": build_user_headers("test-reviewer-1", "RegistrarReviewer"),
    "admin_headers": build_user_headers("test-admin-1", "RegistrarAdmin"),
    "bursar_headers": build_user_headers("test-bursar-1", "BursarOffice"),
    "library_headers": build_user_headers("test-library-1", "LibraryOffice"),
    "archive_headers": build_user_headers("test-archivist-1", "ArchiveClerk"),
    "requester_headers": build_user_headers("test-requester-1", "VerificationRequester"),
}


def make_student_headers(user_id: str) -> dict:
    """For Student (entity_backed:Student). Pass the actual Student.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Student")
