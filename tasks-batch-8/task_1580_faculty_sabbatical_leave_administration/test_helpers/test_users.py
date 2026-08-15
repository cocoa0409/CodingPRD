"""Pre-built role headers for every role in the PRD.

Faculty / CommitteeMember / DepartmentChair are entity-backed roles: their
X-User-ID must equal the acting FacultyMember's id for any ownership-gated
call. Use the per-instance builders below with the real entity id in that
case. The shared constants are only for opaque roles or for tests that never
exercise ownership (bad-payload 400s, 404s, RBAC rejections).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: canonical shared form.
    "provost_headers": build_user_headers("test-provost-1", "ProvostOffice"),
    "admin_headers": build_user_headers("test-admin-1", "LeaveAdministrator"),
    # Entity-backed fallbacks: only for tests that do not exercise ownership.
    "faculty_headers": build_user_headers("test-faculty-1", "Faculty"),
    "committee_headers": build_user_headers("test-committee-1", "CommitteeMember"),
    "chair_headers": build_user_headers("test-chair-1", "DepartmentChair"),
}


def make_faculty_headers(user_id: str) -> dict:
    """Faculty is entity-backed: pass the acting FacultyMember.id."""
    return build_user_headers(user_id, "Faculty")


def make_committee_member_headers(user_id: str) -> dict:
    """CommitteeMember is entity-backed: pass the acting FacultyMember.id."""
    return build_user_headers(user_id, "CommitteeMember")


def make_department_chair_headers(user_id: str) -> dict:
    """DepartmentChair is entity-backed: pass the chairing FacultyMember.id."""
    return build_user_headers(user_id, "DepartmentChair")
