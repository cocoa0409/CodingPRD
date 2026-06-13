"""Pre-built role headers for every role in the PRD.

Member is entity_backed (X-User-ID is the acting Member.id); Anonymous,
StoreOperator, and PlatformAdmin are opaque (X-User-ID is not matched against
any entity). For ownership-gated Member calls, always use make_member_headers
with the real Member id — never the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for non-ownership tests.
TEST_USERS = {
    # Opaque roles: shared constant is the canonical form.
    "anonymous_headers": build_user_headers("anon-user", "Anonymous"),
    "store_operator_headers": build_user_headers("op-user-1", "StoreOperator"),
    "platform_admin_headers": build_user_headers("admin-user-1", "PlatformAdmin"),
    # entity_backed Member: shared constant is a fallback for non-ownership tests
    # (e.g., a Member B used purely to probe a 403 mismatch).
    "member_headers": build_user_headers("member-user-1", "Member"),
}


def make_member_headers(user_id: str) -> dict:
    """For the Member role (entity_backed:Member). Pass the actual Member.id as
    user_id whenever the call is ownership-gated (its own card, orders, rewards)."""
    return build_user_headers(user_id, "Member")


def make_store_operator_headers(user_id: str = "op-user-1") -> dict:
    """StoreOperator is opaque; id is recorded for audit but never owner-matched."""
    return build_user_headers(user_id, "StoreOperator")


def make_platform_admin_headers(user_id: str = "admin-user-1") -> dict:
    """PlatformAdmin is opaque; id is never owner-matched."""
    return build_user_headers(user_id, "PlatformAdmin")
