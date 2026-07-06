"""Pre-built role headers for every role in the PRD.

Member is entity_backed (X-User-ID is the acting Member.id and is compared to a
resource's member_id for ownership). StoreClerk and InventoryManager are opaque
operator identities never matched against any entity id. Anonymous carries no
role header at all and is used only to probe the 401 authentication gate.

For ownership-gated Member calls, always build per-instance headers via
make_member_headers(member_id) with the real Member.id — never the shared
constant, whose id never equals any real member's id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the two opaque roles, and for tests that don't
# exercise Member ownership.
TEST_USERS = {
    # Opaque roles: the shared constant is the canonical form.
    "store_clerk_headers": build_user_headers("clerk-op-1", "StoreClerk"),
    "inventory_manager_headers": build_user_headers("im-op-1", "InventoryManager"),
    # entity_backed Member: shared constant is a fallback for non-ownership probes.
    "member_headers": build_user_headers("member-user-1", "Member"),
    # Anonymous: no role header — trips ERR_UNAUTHENTICATED.
    "anonymous_headers": {"Content-Type": "application/json"},
}


def make_member_headers(user_id: str) -> dict:
    """For the Member role (entity_backed:Member). Pass the actual Member.id as
    user_id whenever the call is ownership-gated (own orders/containers/subs)."""
    return build_user_headers(user_id, "Member")


def make_store_clerk_headers(user_id: str = "clerk-op-1") -> dict:
    """StoreClerk is opaque; the id is recorded for audit but never owner-matched."""
    return build_user_headers(user_id, "StoreClerk")


def make_inventory_manager_headers(user_id: str = "im-op-1") -> dict:
    """InventoryManager is opaque; the id is never owner-matched."""
    return build_user_headers(user_id, "InventoryManager")
