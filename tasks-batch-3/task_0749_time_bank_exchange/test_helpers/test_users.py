"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for non-ownership tests.
TEST_USERS = {
    # entity_backed:Member — shared constant for non-ownership tests only.
    "member_headers": build_user_headers("test-member-1", "Member"),
    # entity_backed:Member — shared constant for non-ownership tests only.
    "organizer_headers": build_user_headers("test-organizer-1", "ProjectOrganizer"),
    # opaque — shared constant is the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    # unauthenticated placeholder — used for missing-header tests
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
}


# Per-instance builders — mandatory for every entity_backed role.
def make_member_headers(member_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(member_id, "Member")


def make_organizer_headers(member_id: str) -> dict:
    """For ProjectOrganizer (entity_backed:Member). Pass the actual Member.id
    of the organizer whenever the call is ownership-gated on organizer_member_id."""
    return build_user_headers(member_id, "ProjectOrganizer")


def make_admin_headers(operator_id: str = "test-admin-1") -> dict:
    """PlatformAdmin identity is opaque; the operator string is not
    resource-scoped. Convenience shim that mirrors the entity_backed builders."""
    return build_user_headers(operator_id, "PlatformAdmin")


def unauthenticated_headers() -> dict:
    """No X-User-Role / X-User-ID. Used only for ERR_UNAUTHENTICATED tests."""
    return {}
