"""Pre-built role headers for every role in the Art Auction Consignment PRD.

Six roles (PRD §2.1): SaleAdministrator, Auctioneer, FinanceOfficer, Viewer
are opaque operator identities whose X-User-ID is not compared against any
entity. Seller and Bidder are entity-backed: when X-User-Role is Seller,
X-User-ID is the acting Seller.id; when it is Bidder, X-User-ID is the acting
Bidder.id, and ownership checks compare the resource's owning FK against it.
For ownership-gated calls by an entity-backed role, use the per-instance
builder with the real entity id; the shared constant is a fallback only for
non-ownership paths (403/404/400 checks).
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "SaleAdministrator"),
    "auctioneer_headers": build_user_headers("test-auctioneer-1", "Auctioneer"),
    "finance_headers": build_user_headers("test-finance-1", "FinanceOfficer"),
    "viewer_headers": build_user_headers("test-viewer-1", "Viewer"),
    # Entity-backed shared fallbacks (non-ownership paths only).
    "seller_headers": build_user_headers("test-seller-1", "Seller"),
    "bidder_headers": build_user_headers("test-bidder-1", "Bidder"),
}


def make_seller_headers(seller_id: str) -> dict:
    """For Seller (entity_backed:Seller). Pass the acting Seller.id as X-User-ID
    whenever the call is ownership-gated."""
    return build_user_headers(seller_id, "Seller")


def make_bidder_headers(bidder_id: str) -> dict:
    """For Bidder (entity_backed:Bidder). Pass the acting Bidder.id as X-User-ID
    whenever the call is ownership-gated (e.g. a bidder bidding on its own
    paddle)."""
    return build_user_headers(bidder_id, "Bidder")


def make_role_headers(user_id: str, role: str) -> dict:
    """Build headers for an arbitrary (possibly unrecognized) role string. Used
    by negative auth tests."""
    return build_user_headers(user_id, role)
