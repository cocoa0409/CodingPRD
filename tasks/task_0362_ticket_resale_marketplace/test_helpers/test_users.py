"""Pre-built role headers for every role in the PRD (§2.1).

PlatformAdmin and TrustSafety are opaque operator roles: their X-User-ID is not
tied to any entity, so the shared constants are the canonical form.

Seller and Buyer are entity_backed: their X-User-ID must equal the acting
Seller.id / Buyer.id for ownership checks to pass. For ownership-gated calls,
fixtures MUST use make_seller_headers(seller["id"]) / make_buyer_headers(
buyer["id"]) with the real entity id — never the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — opaque operators (canonical), plus entity_backed fallbacks
# used ONLY by tests that do not exercise ownership (e.g. 400/401/403/404 paths).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("ops-admin-1", "PlatformAdmin"),
    "trust_safety_headers": build_user_headers("ops-trust-1", "TrustSafety"),
    # entity_backed fallbacks: do NOT use for ownership-gated success paths.
    "seller_headers": build_user_headers("test-seller-1", "Seller"),
    "buyer_headers": build_user_headers("test-buyer-1", "Buyer"),
}


# Per-instance builders — REQUIRED for every entity_backed role.
def make_seller_headers(user_id: str) -> dict:
    """For a Seller (entity_backed:Seller). Pass the real Seller.id as user_id
    whenever the call is ownership-gated (listing/seat/transfer/payout ops)."""
    return build_user_headers(user_id, "Seller")


def make_buyer_headers(user_id: str) -> dict:
    """For a Buyer (entity_backed:Buyer). Pass the real Buyer.id as user_id
    whenever the call is ownership-gated (order/claim/credit ops)."""
    return build_user_headers(user_id, "Buyer")


def make_platform_admin_headers(user_id: str = "ops-admin-1") -> dict:
    """For PlatformAdmin (opaque). Any operator id is acceptable."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_trust_safety_headers(user_id: str = "ops-trust-1") -> dict:
    """For TrustSafety (opaque). Any operator id is acceptable."""
    return build_user_headers(user_id, "TrustSafety")
