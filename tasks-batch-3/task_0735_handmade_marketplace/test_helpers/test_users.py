"""Pre-built role headers for every role in the PRD.

Roles (PRD §2.1): Seller (entity-backed by the shop — X-User-ID is the shop id),
Buyer (opaque identity captured onto orders as buyer_id), and PlatformAdmin (opaque
operator identity). Ownership on Seller mutations compares the resource's shop_id to
X-User-ID; ownership on Buyer actions compares the order's buyer_id to X-User-ID.
"""
from prd_bench_local_runner.testing import build_user_headers

SELLER_ROLE = "Seller"
BUYER_ROLE = "Buyer"
ADMIN_ROLE = "PlatformAdmin"


# Shared constants — safe for opaque roles (PlatformAdmin, Buyer default) and for
# tests whose success does not depend on the caller owning the subject resource.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("admin-1", ADMIN_ROLE),
    "buyer_headers": build_user_headers("buyer_1", BUYER_ROLE),
    # Seller is entity_backed:Shop — this shared constant is a NON-ownership fallback
    # only (its X-User-ID equals no real shop id). Ownership-gated seller calls MUST
    # use make_seller_headers(shop_id) instead.
    "seller_headers": build_user_headers("seller-no-shop", SELLER_ROLE),
}


# Per-instance builders.
def make_seller_headers(shop_id: str) -> dict:
    """For the Seller role (entity_backed:Shop). Pass the acting shop's id as the
    X-User-ID whenever the call is ownership-gated (all shop-scoped mutations)."""
    return build_user_headers(shop_id, SELLER_ROLE)


def make_buyer_headers(buyer_id: str) -> dict:
    """For the Buyer role. The opaque buyer id is captured as order.buyer_id and later
    matched for ownership on pay/complete/review/case actions."""
    return build_user_headers(buyer_id, BUYER_ROLE)


def make_admin_headers(admin_id: str = "admin-1") -> dict:
    """For the PlatformAdmin role (opaque operator identity)."""
    return build_user_headers(admin_id, ADMIN_ROLE)


def anonymous_headers() -> dict:
    """No auth headers — used to exercise ERR_UNAUTHENTICATED."""
    return {}
