"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque PlatformAdmin role, and for tests that
# do not exercise ownership (e.g. 400-on-bad-payload, 404-on-missing-resource).
TEST_USERS = {
    # PlatformAdmin identity is opaque: X-User-ID is not tied to any entity.
    "platform_admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "creator_headers": build_user_headers("creator-shared", "Creator"),
    "student_headers": build_user_headers("student-shared", "Student"),
}


def make_platform_admin_headers(user_id: str = "admin-1") -> dict:
    """PlatformAdmin is opaque; any operator id is accepted."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_creator_headers(user_id: str) -> dict:
    """For Creator (entity_backed:Creator). Pass the actual Creator.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Creator")


def make_student_headers(user_id: str) -> dict:
    """For Student (entity_backed:Student). Pass the actual Student.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Student")
