"""Pre-built role headers for the five PRD roles.

EventOrganizer, AuctionManager and FinanceOfficer carry opaque operator
identifiers, so the shared constants below are the canonical form for them.
Bidder and Sponsor are entity-backed: X-User-ID must be the acting Bidder's or
Sponsor's own id, so ownership-gated calls must use the per-instance builders.
"""
from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    AUCTION_USER_ID,
    FINANCE_USER_ID,
    FINANCE_USER_ID_2,
    ORG_USER_ID,
)

TEST_USERS = {
    # Opaque operator roles — the shared constant is canonical.
    "organizer_headers": build_user_headers(ORG_USER_ID, "EventOrganizer"),
    "auction_manager_headers": build_user_headers(AUCTION_USER_ID, "AuctionManager"),
    "finance_headers": build_user_headers(FINANCE_USER_ID, "FinanceOfficer"),
    "finance_headers_2": build_user_headers(FINANCE_USER_ID_2, "FinanceOfficer"),
    # Entity-backed roles — fallback only for tests that never touch ownership
    # (malformed payloads, missing resources, forbidden-role checks).
    "bidder_headers": build_user_headers("test-bidder-1", "Bidder"),
    "sponsor_headers": build_user_headers("test-sponsor-1", "Sponsor"),
}


def make_bidder_headers(bidder_id: str) -> dict:
    """Headers for the Bidder role. Pass the acting guest's own id whenever the
    call is ownership-gated (bidding, holds, ticket orders, payments,
    payment-method updates)."""
    return build_user_headers(bidder_id, "Bidder")


def make_sponsor_headers(sponsor_id: str) -> dict:
    """Headers for the Sponsor role. Pass the acting sponsoring organization's
    own id whenever the call is ownership-gated (ad submission, resubmission)."""
    return build_user_headers(sponsor_id, "Sponsor")


def make_finance_headers(user_id: str) -> dict:
    """Headers for an arbitrary FinanceOfficer operator id, for the two
    segregation-of-duties surfaces."""
    return build_user_headers(user_id, "FinanceOfficer")


def make_organizer_headers(user_id: str) -> dict:
    """Headers for an arbitrary EventOrganizer operator id."""
    return build_user_headers(user_id, "EventOrganizer")
