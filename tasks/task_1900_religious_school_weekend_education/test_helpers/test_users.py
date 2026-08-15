"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # opaque role: shared constant is the canonical form.
    "admin_headers": build_user_headers("admin-1", "SchoolAdmin"),
    "officer_headers": build_user_headers("officer-1", "AssistanceOfficer"),
    "officer2_headers": build_user_headers("officer-2", "AssistanceOfficer"),
    # entity_backed roles: shared constants are a fallback for non-ownership tests only.
    "teacher_headers": build_user_headers("test-teacher-1", "Teacher"),
    "parent_headers": build_user_headers("test-parent-1", "Parent"),
}


def make_admin_headers(user_id: str = "admin-1") -> dict:
    """SchoolAdmin is opaque; any identifier works, but SoD tests need distinct ones."""
    return build_user_headers(user_id, "SchoolAdmin")


def make_officer_headers(user_id: str = "officer-1") -> dict:
    """AssistanceOfficer is opaque; distinct ids support segregation-of-duties flows."""
    return build_user_headers(user_id, "AssistanceOfficer")


def make_teacher_headers(user_id: str) -> dict:
    """For Teacher (entity_backed:Teacher). Pass the actual Teacher.id as user_id
    whenever the call is ownership-gated (attendance posting)."""
    return build_user_headers(user_id, "Teacher")


def make_parent_headers(user_id: str) -> dict:
    """For Parent (entity_backed:Family). Pass the actual Family.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Parent")
