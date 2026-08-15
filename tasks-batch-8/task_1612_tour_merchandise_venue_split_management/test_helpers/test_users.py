"""Pre-built role headers for every role in the PRD.

TourManager / Accountant / VenueRep are opaque roles: their X-User-ID is not
compared to any entity id, so shared constants are canonical.

Seller is entity-backed (X-User-ID must be the id of an existing Seller):
ownership-gated calls MUST use make_seller_headers(<seller id>). The shared
"seller_headers" constant is only a fallback for tests that do not exercise
ownership (e.g., role-denied calls).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "tour_manager_headers": build_user_headers("tm-1", "TourManager"),
    "tour_manager_2_headers": build_user_headers("tm-2", "TourManager"),
    "accountant_headers": build_user_headers("acct-1", "Accountant"),
    "accountant_2_headers": build_user_headers("acct-2", "Accountant"),
    "venue_rep_headers": build_user_headers("venue-1", "VenueRep"),
    # Fallback only: "seller-nobody" is not a real Seller id, so the auth
    # layer itself would reject it. Ownership-gated calls must use the builder.
    "seller_headers": build_user_headers("seller-nobody", "Seller"),
}


def make_seller_headers(user_id: str) -> dict:
    """For Seller (entity-backed: Seller). Pass the actual Seller.id as
    user_id whenever the call is ownership-gated or the role must resolve."""
    return build_user_headers(user_id, "Seller")
