"""Pre-built role headers for every role in the PRD (§2.1).

AidDirector and AidOfficer are opaque identities: X-User-ID is not tied to any
persisted entity, though the server may record it (e.g. `opened_by_user_id`,
`reviewed_by_user_id`, `resolved_by_user_id`) for segregation-of-duties checks.
Student is entity-backed: X-User-ID IS the acting Student's `id`, and ownership
checks compare it to the package's `student_id`. Ownership-gated calls MUST use
make_student_headers(student["id"]) — never the shared fallback constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership (400-on-bad-payload, 404-on-missing-resource, wrong-role checks).
TEST_USERS = {
    "aid_director_headers": build_user_headers("test-aid-director-1", "AidDirector"),
    "aid_officer_headers": build_user_headers("test-aid-officer-1", "AidOfficer"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "student_headers": build_user_headers("test-student-1", "Student"),
}


def make_aid_director_headers(user_id: str = "test-aid-director-1") -> dict:
    """AidDirector is opaque; pass a distinct user_id when a segregation rule
    compares recorded user ids."""
    return build_user_headers(user_id, "AidDirector")


def make_aid_officer_headers(user_id: str = "test-aid-officer-1") -> dict:
    """AidOfficer is opaque; pass a distinct user_id (e.g. 'officer-alpha' vs
    'officer-beta') when a segregation-of-duties rule compares recorded ids."""
    return build_user_headers(user_id, "AidOfficer")


def make_student_headers(student_id: str) -> dict:
    """For Student (entity_backed:Student). Pass the acting Student.id whenever
    the call is ownership-gated (accept/decline/revision-requests/acknowledge)."""
    return build_user_headers(student_id, "Student")
