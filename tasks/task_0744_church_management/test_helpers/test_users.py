"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers


# Shared constants — safe for opaque roles, and for tests that don't exercise
# per-member ownership checks. Member is entity_backed:Member, so use the
# builder below for any ownership-gated call.
TEST_USERS = {
    "registrar_headers": build_user_headers("op-registrar-1", "Registrar"),
    "finance_admin_headers": build_user_headers("op-finance-1", "FinanceAdmin"),
    "coordinator_headers": build_user_headers("op-coord-1", "Coordinator"),
    "platform_admin_headers": build_user_headers("op-admin-1", "PlatformAdmin"),
    # Fallback for member calls that don't hit ownership checks (rare).
    "member_headers": build_user_headers("test-member-fallback", "Member"),
    # Unknown role — for triggering ERR_UNAUTHENTICATED.
    "unknown_role_headers": build_user_headers("op-ghost-1", "Ghost"),
}


def make_member_headers(member_id: str) -> dict:
    """For Member (entity_backed:Member). Pass the acting Member.id as user_id
    whenever the call is ownership-gated (create own pledge/donation, RSVP own
    volunteer invitation, etc.). Falling back to a shared constant for member
    calls is the canonical bug: X-User-ID would never equal any real Member.id
    and every ownership check would reject the request."""
    return build_user_headers(member_id, "Member")
