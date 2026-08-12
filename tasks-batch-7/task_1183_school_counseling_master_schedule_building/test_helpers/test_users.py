"""Pre-built role headers for every role in the PRD.

Administrator is an opaque role: the server never derives resource ownership
from its X-User-ID. Counselor and Student are entity-backed roles: their
X-User-ID MUST equal the id of the persisted Counselor / Student row whenever
the call is ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque role, and for tests that don't exercise ownership.
TEST_USERS = {
    # opaque role: shared constant is the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "Administrator"),
    # entity_backed roles: shared constants are a fallback for non-ownership tests only.
    "counselor_headers": build_user_headers("test-counselor-1", "Counselor"),
    "student_headers": build_user_headers("test-student-1", "Student"),
}


# Per-instance builders — required for every entity_backed role.
def make_counselor_headers(user_id: str) -> dict:
    """For Counselor (entity_backed:Counselor). Pass the actual Counselor.id as
    user_id whenever the call is ownership-gated (claim, return-for-revision,
    appointment complete / mark-no-show, recovery create / place)."""
    return build_user_headers(user_id, "Counselor")


def make_student_headers(user_id: str) -> dict:
    """For Student (entity_backed:Student). Pass the actual Student.id as
    user_id whenever the call is ownership-gated (request submit / unsubmit /
    delete, change-request create / resubmit / cancel, own-schedule reads)."""
    return build_user_headers(user_id, "Student")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """For Administrator (opaque). Pass a distinct user_id when the call must
    differ from a reviewing counselor's id (segregation of duties)."""
    return build_user_headers(user_id, "Administrator")
