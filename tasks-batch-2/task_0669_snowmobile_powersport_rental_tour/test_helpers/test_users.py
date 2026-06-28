"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # opaque roles: shared constant is the canonical form.
    "dispatch_headers": build_user_headers("test-dispatch-1", "DispatchOperator"),
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "anonymous_headers": build_user_headers("test-anon-1", "Anonymous"),
    # entity_backed roles: shared constant is a fallback for non-ownership tests only
    # (e.g., 403 role-denial, 404 not-found). Ownership-gated calls MUST use the
    # per-instance builder below threaded with the real entity id.
    "member_headers": build_user_headers("test-member-1", "Member"),
    "guide_headers": build_user_headers("test-guide-1", "Guide"),
}


# Per-instance builders — required for every entity_backed role.
def make_member_headers(user_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the actual Member.id as user_id
    whenever the call is ownership-gated (confirm/cancel a reservation)."""
    return build_user_headers(user_id, "Member")


def make_guide_headers(user_id: str) -> dict:
    """For Guide (entity_backed:Guide). Pass the actual Guide.id as user_id
    whenever the call is ownership-gated (depart/complete a departure)."""
    return build_user_headers(user_id, "Guide")


def anonymous_headers() -> dict:
    """Anonymous caller (self-registration). The framework still sends headers;
    registration is the lone endpoint exempt from the authentication requirement."""
    return build_user_headers("anon", "Anonymous")
