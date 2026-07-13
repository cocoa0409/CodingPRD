"""Pre-built role headers for every role in the Auction House PRD (§2.1).

Three roles are operational with opaque identity (AuctionStaff, Appraiser,
SettlementOfficer): the shared constant is the canonical form.

Two roles are entity-backed principals (Consignor -> Consignor.id,
Bidder -> Bidder.id): ownership-gated calls MUST use the per-instance builder
with the real entity id, or every ownership check rejects the request.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # Opaque operational roles — shared constant is canonical.
    "staff_headers": build_user_headers("staff-1", "AuctionStaff"),
    "appraiser_headers": build_user_headers("appraiser-1", "Appraiser"),
    "settlement_headers": build_user_headers("settlement-1", "SettlementOfficer"),
    # Entity-backed roles — shared constant is a fallback for non-ownership tests only.
    "bidder_headers": build_user_headers("bidder-fallback-1", "Bidder"),
    "consignor_headers": build_user_headers("consignor-fallback-1", "Consignor"),
}


def make_bidder_headers(user_id: str) -> dict:
    """For the Bidder role (entity-backed by Bidder). Pass the actual Bidder.id
    as user_id whenever the call is ownership-gated (bid placement, invoice
    payment, dispute filing)."""
    return build_user_headers(user_id, "Bidder")


def make_consignor_headers(user_id: str) -> dict:
    """For the Consignor role (entity-backed by Consignor). Pass the actual
    Consignor.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Consignor")
