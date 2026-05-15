"""Bidding mechanics: increment ladder, bid cap, soft-close extension,
deposit-paid precondition, bidder-status precondition (PRD §3.5, §3.6).
"""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    api_client,
    create_bid_payload,
    create_bidder_account,
    INC_TIER_1_CENTS,
    INC_TIER_2_CENTS,
    INC_TIER_3_CENTS,
    INC_TIER_4_CENTS,
    iso_utc,
    make_bidder_headers,
    place_bid,
    setup_announced_lot,
    setup_bidder_with_paid_deposit,
    setup_live_auction,
    TIER_1_MAX_CENTS,
    TIER_2_MAX_CENTS,
    TIER_3_MAX_CENTS,
    validate_error,
    validate_success,
)


def _parse(value):
    from datetime import datetime
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


# ===========================================================================
# Increment ladder — PRD §3.5
# ===========================================================================
class TestBidIncrementLadder:

    def test_first_bid_can_equal_starting_price(self, api):
        """PRD §3.5: "When no valid bid exists yet, the very first bid may equal `starting_price_cents` exactly — the ladder increment does not apply to the opening bid."

        Claim: first bid at amount == starting_price → 201.
        """
        # starting_price = 70_000_000 at the default assessment.
        _lot, auction, bidders = setup_live_auction(
            num_bidders=1, assessment_value_cents=100_000_000,
        )
        bidder, _ = bidders[0]
        resp = api.create_bid(
            create_bid_payload(auction["id"], 70_000_000, client_seq_no=1),
            make_bidder_headers(bidder["id"]),
        )
        validate_success(resp, expected_status=201)

    def test_subsequent_bid_below_increment_minimum_rejected(self, api):
        """PRD §3.5: "When at least one valid bid already exists, the minimum acceptable next bid is the current high plus the applicable increment, and the submitted `amount_cents` must be greater than or equal to that minimum (equality is accepted)."

        And PRD §3.5: "If the base is at least fifty million cents but strictly less than two hundred million cents (that is, less than two million units), the increment is five hundred thousand cents (five thousand units)."

        Claim: with current_high = 70_000_000 (tier-2 base), a bid at
        70_000_001 (well below +500_000 increment minimum 70_500_000)
        → ERR_BID_NOT_ABOVE_HIGH.
        """
        _lot, auction, bidders = setup_live_auction(
            num_bidders=2, assessment_value_cents=100_000_000,
        )
        bidder_a, _ = bidders[0]
        bidder_b, _ = bidders[1]
        # Bidder A bids the starting price 70_000_000.
        place_bid(auction["id"], bidder_a["id"], 70_000_000, client_seq_no=1)
        # Bidder B tries 70_000_001 — below the 70_500_000 minimum.
        resp = api.create_bid(
            create_bid_payload(auction["id"], 70_000_001, client_seq_no=1),
            make_bidder_headers(bidder_b["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BID_NOT_ABOVE_HIGH.value)

    def test_subsequent_bid_at_increment_minimum_accepted(self, api):
        """PRD §3.5: "equality is accepted" at the minimum next bid.

        Claim: with current_high = 70_000_000 → minimum = 70_500_000;
        a bid at exactly 70_500_000 → 201.
        """
        _lot, auction, bidders = setup_live_auction(
            num_bidders=2, assessment_value_cents=100_000_000,
        )
        bidder_a, _ = bidders[0]
        bidder_b, _ = bidders[1]
        place_bid(auction["id"], bidder_a["id"], 70_000_000, client_seq_no=1)
        resp = api.create_bid(
            create_bid_payload(auction["id"], 70_500_000, client_seq_no=1),
            make_bidder_headers(bidder_b["id"]),
        )
        validate_success(resp, expected_status=201)


# ===========================================================================
# Bid cap — PRD §3.5
# ===========================================================================
class TestBidCap:

    def test_bid_strictly_above_cap_rejected(self, api):
        """PRD §3.5: "If the auction's `bid_cap_cents` is not null, `amount_cents` must not be strictly greater than the cap; equality with the cap is accepted, but any value above the cap is rejected with `ERR_BID_AT_OR_ABOVE_CAP."

        Claim: bid amount = cap + 1 → ERR_BID_AT_OR_ABOVE_CAP.
        """
        _lot, auction, bidders = setup_live_auction(
            num_bidders=1, assessment_value_cents=100_000_000,
            bid_cap_cents=80_000_000,
        )
        bidder, _ = bidders[0]
        resp = api.create_bid(
            create_bid_payload(auction["id"], 80_000_001, client_seq_no=1),
            make_bidder_headers(bidder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BID_AT_OR_ABOVE_CAP.value)

    def test_bid_equal_to_cap_accepted(self, api):
        """PRD §3.5: "equality with the cap is accepted."

        Claim: bid amount == bid_cap_cents → 201.
        """
        _lot, auction, bidders = setup_live_auction(
            num_bidders=1, assessment_value_cents=100_000_000,
            bid_cap_cents=80_000_000,
        )
        bidder, _ = bidders[0]
        resp = api.create_bid(
            create_bid_payload(auction["id"], 80_000_000, client_seq_no=1),
            make_bidder_headers(bidder["id"]),
        )
        validate_success(resp, expected_status=201)


# ===========================================================================
# Deposit precondition — PRD §3.5
# ===========================================================================
class TestBidDepositPrecondition:

    def test_bid_without_paid_deposit_rejected(self, api):
        """PRD §3.5: "The bidder must already have a `Deposit` on this `auction_id` in `PAID` status; otherwise the bid is rejected with `ERR_DEPOSIT_NOT_PAID."

        Claim: bidder without PAID deposit attempts bid →
        ERR_DEPOSIT_NOT_PAID.
        """
        _lot, auction, _bidders = setup_live_auction(num_bidders=0)
        bidder = create_bidder_account()
        resp = api.create_bid(
            create_bid_payload(
                auction["id"], auction["starting_price_cents"],
                client_seq_no=1,
            ),
            make_bidder_headers(bidder["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DEPOSIT_NOT_PAID.value)


# ===========================================================================
# Soft-close extension — PRD §3.5
# ===========================================================================
class TestSoftCloseExtension:

    def test_soft_close_boundary_strict_less_than(self, api):
        """PRD §3.5: "If the remaining time until `effective_end_at` is strictly less than `soft_close_window_seconds`, the auction's `effective_end_at` is reset to the current instant plus `soft_close_extension_seconds`. The comparison is strict — a bid arriving exactly at the boundary (with the remaining time equal to `soft_close_window_seconds`) does not extend; a bid one second further inside the window does."

        Claim: bid at delta == 300 (boundary) does NOT extend;
        next bid at delta == 299 DOES extend.
        """
        _lot, auction, bidders = setup_live_auction(
            num_bidders=2,
            assessment_value_cents=100_000_000,
            soft_close_window_seconds=300,
            soft_close_extension_seconds=300,
        )
        bidder_a, _ = bidders[0]
        bidder_b, _ = bidders[1]
        end_at = _parse(auction["effective_end_at"])
        # Advance clock so remaining time = 300s exactly.
        advance_clock_to(end_at - timedelta(seconds=300))
        place_bid(auction["id"], bidder_a["id"], 70_000_000, client_seq_no=1)
        from test_helpers import get_auction
        a1 = get_auction(auction["id"])
        assert a1["effective_end_at"] == auction["effective_end_at"], (
            "Bid at delta = soft_close_window_seconds must NOT extend "
            "(strict less-than boundary)"
        )
        # Advance one more second so remaining = 299s.
        advance_clock_to(end_at - timedelta(seconds=299))
        place_bid(auction["id"], bidder_b["id"], 70_500_000, client_seq_no=1)
        a2 = get_auction(auction["id"])
        assert a2["effective_end_at"] != auction["effective_end_at"], (
            "Bid at delta < soft_close_window_seconds must extend"
        )


# ===========================================================================
# Bid masking — PRD §2.11
# ===========================================================================
class TestBidMaskedHandle:

    def test_bid_response_carries_masked_handle(self, api):
        """PRD §2.11: "every `Bid` carries a server-computed `masked_handle` (for example"Bidder #042") that is rendered to non-CourtClerk
        callers."

        Claim: POST /bids response (Bidder caller) includes a non-empty
        masked_handle.
        """
        _lot, auction, bidders = setup_live_auction(
            num_bidders=1, assessment_value_cents=100_000_000,
        )
        bidder, _ = bidders[0]
        resp = api.create_bid(
            create_bid_payload(auction["id"], 70_000_000, client_seq_no=1),
            make_bidder_headers(bidder["id"]),
        )
        bid = validate_success(resp, expected_status=201)
        assert isinstance(bid.get("masked_handle"), str) \
            and bid["masked_handle"], "masked_handle must be non-empty"
