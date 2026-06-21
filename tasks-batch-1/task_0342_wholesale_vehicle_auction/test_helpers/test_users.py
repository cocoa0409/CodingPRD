"""Pre-built role headers for every role in the PRD (§2.1).

AuctionAdmin and Arbitrator are opaque identities: their X-User-ID is not bound
to any persisted entity, so the shared constants below are the canonical form.

Seller and Buyer are entity_backed: their X-User-ID must equal the acting
entity's id for any ownership-gated write. Use make_seller_headers(seller_id) /
make_buyer_headers(buyer_id) with the actual entity id in those cases. The shared
constants are only safe for tests that do NOT exercise ownership (e.g. 401/403
role checks, or as the not-yet-known fallback).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constant is the canonical form.
    "auction_admin_headers": build_user_headers("test-admin-1", "AuctionAdmin"),
    "arbitrator_headers": build_user_headers("test-arbitrator-1", "Arbitrator"),
    # entity_backed roles — shared constants are fallbacks for non-ownership tests only.
    "seller_headers": build_user_headers("test-seller-1", "Seller"),
    "buyer_headers": build_user_headers("test-buyer-1", "Buyer"),
}


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """AuctionAdmin (opaque). X-User-ID is an arbitrary operator identifier."""
    return build_user_headers(user_id, "AuctionAdmin")


def make_arbitrator_headers(user_id: str = "test-arbitrator-1") -> dict:
    """Arbitrator (opaque). X-User-ID is an arbitrary adjudicator identifier."""
    return build_user_headers(user_id, "Arbitrator")


def make_seller_headers(seller_id: str) -> dict:
    """Seller (entity_backed:Seller). Pass the actual Seller.id for ownership-gated calls."""
    return build_user_headers(seller_id, "Seller")


def make_buyer_headers(buyer_id: str) -> dict:
    """Buyer (entity_backed:Buyer). Pass the actual Buyer.id for ownership-gated calls
    (placing bids, opening arbitration claims, booking/cancelling transport)."""
    return build_user_headers(buyer_id, "Buyer")
