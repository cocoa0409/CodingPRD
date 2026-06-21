"""Pre-built role headers for every role in the PRD (Section 2.1).

Per the PRD, Anonymous / Moderator / PlatformAdmin carry an opaque X-User-ID
not tied to any entity, so a shared constant is the canonical form for them.
Seller / Buyer / Member are facets of an entity-backed Member: their X-User-ID
must equal the acting Member's id whenever an ownership check applies, so the
per-instance builders below MUST be used in those cases.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
#  - Opaque roles (Moderator, PlatformAdmin, Anonymous): canonical form.
#  - Entity-backed roles (Seller, Buyer, Member): a fallback usable ONLY for
#    tests that do not exercise ownership (e.g. 401/403-by-role/404 paths).
TEST_USERS = {
    "anonymous_headers": build_user_headers("anon-public-1", "Anonymous"),
    "moderator_headers": build_user_headers("mod-operator-1", "Moderator"),
    "platform_admin_headers": build_user_headers("admin-operator-1", "PlatformAdmin"),
    "seller_headers": build_user_headers("seller-fallback-1", "Seller"),
    "buyer_headers": build_user_headers("buyer-fallback-1", "Buyer"),
    "member_headers": build_user_headers("member-fallback-1", "Member"),
}


# --- Per-instance builders for entity-backed roles (mandatory for ownership) ---

def make_seller_headers(user_id: str) -> dict:
    """Seller role; pass the owning Member.id for ownership-gated listing ops."""
    return build_user_headers(user_id, "Seller")


def make_buyer_headers(user_id: str) -> dict:
    """Buyer role; pass the acting Member.id for buyer-scoped ops."""
    return build_user_headers(user_id, "Buyer")


def make_member_headers(user_id: str) -> dict:
    """Generic Member role; pass the acting Member.id for participant/owner ops."""
    return build_user_headers(user_id, "Member")


def make_moderator_headers(user_id: str = "mod-operator-1") -> dict:
    """Moderator is opaque; user_id is recorded but not compared to any entity."""
    return build_user_headers(user_id, "Moderator")


def make_admin_headers(user_id: str = "admin-operator-1") -> dict:
    """PlatformAdmin is opaque; user_id is recorded but not compared to any entity."""
    return build_user_headers(user_id, "PlatformAdmin")
