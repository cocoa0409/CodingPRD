"""Tests for PRD §3.3 — Bidding on AUCTION listings: tiered increment rule,
deposit hold (10% rounded up), cyclic LIVE↔OUTBID, cancellation, close-auction
with reserve.
"""

import math

import pytest

from test_helpers import (
    api_client,
    assert_bid,
    create_bid_payload,
    make_buyer_headers,
    place_bid,
    register_buyer,
    setup_active_listing,
    setup_auction_with_two_bidders,
    validate_error,
    validate_success,
)


# ──────────────────────────────────────────────────────────
# §3.3 Bid increment — three tiers
# ──────────────────────────────────────────────────────────


def test_first_bid_at_ask_plus_low_increment_succeeds(api):
    """PRD §3.3: "the current maximum, which is the amount_cents of the
    listing's current LIVE bid (read via the listing's active_bid_id) if one
    exists, or the listing's ask_price_cents if none has been placed yet.
    When the current maximum is below the first-tier ceiling of fifty
    thousand currency units (five million cents), the required increment is
    five hundred currency units (fifty thousand cents)."

    Setup: ask=1_000_000 (below 5_000_000), first bid must be >= 1_050_000.
    """
    _, listing, _, buyer_a, _ = setup_auction_with_two_bidders(
        ask_price_cents=1_000_000, reserve_price_cents=1_000_000
    )
    bid = place_bid(buyer_a, listing, 1_050_000)
    assert_bid(bid)
    assert bid["status"] == "LIVE"
    assert bid["amount_cents"] == 1_050_000


def test_first_bid_one_below_required_min_rejected_low_tier(api):
    """PRD §3.3: "The new bid's amount_cents must be at least the current
    maximum plus the applicable increment; equality at the boundary fails
    (the required minimum is strictly above the current maximum by the
    increment). A bid below the required minimum is rejected with
    ERR_BID_TOO_LOW."

    Setup: ask=1_000_000; required_min = 1_050_000; bid 1_049_999 fails.
    """
    _, listing, _, buyer_a, _ = setup_auction_with_two_bidders(
        ask_price_cents=1_000_000, reserve_price_cents=1_000_000
    )
    res = api.place_bid(
        listing["id"],
        create_bid_payload(1_049_999),
        make_buyer_headers(buyer_a["id"]),
    )
    validate_error(res, "ERR_BID_TOO_LOW")


def test_first_bid_equal_to_current_max_rejected(api):
    """PRD §3.3: "equality at the boundary fails (the required minimum is
    strictly above the current maximum by the increment)."

    Setup: ask=1_000_000; bid exactly 1_000_000 must fail (must be >= 1_050_000).
    """
    _, listing, _, buyer_a, _ = setup_auction_with_two_bidders(
        ask_price_cents=1_000_000, reserve_price_cents=1_000_000
    )
    res = api.place_bid(
        listing["id"],
        create_bid_payload(1_000_000),
        make_buyer_headers(buyer_a["id"]),
    )
    validate_error(res, "ERR_BID_TOO_LOW")


def test_mid_tier_bid_increment_two_hundred_thousand_cents(api):
    """PRD §3.3: "When the current maximum is at least the first-tier ceiling
    but below the second-tier ceiling of two hundred thousand currency units
    (twenty million cents), the required increment is two thousand currency
    units (two hundred thousand cents)."

    Setup: ask=5_000_000 (== first-tier ceiling); required increment = 200_000.
    A bid of 5_200_000 succeeds; 5_199_999 fails.
    """
    _, listing, _, buyer_a, _ = setup_auction_with_two_bidders(
        ask_price_cents=5_000_000, reserve_price_cents=5_000_000
    )
    bid = place_bid(buyer_a, listing, 5_200_000)
    assert bid["amount_cents"] == 5_200_000


def test_mid_tier_one_below_increment_rejected(api):
    """PRD §3.3: "When the current maximum is at least the first-tier ceiling
    but below the second-tier ceiling of two hundred thousand currency units
    (twenty million cents), the required increment is two thousand currency
    units (two hundred thousand cents)."
    PRD §3.3: "A bid below the required minimum is rejected with
    ERR_BID_TOO_LOW."

    Setup: ask=5_000_000 (mid tier); required=5_200_000; bid 5_199_999 fails.
    """
    _, listing, _, buyer_a, _ = setup_auction_with_two_bidders(
        ask_price_cents=5_000_000, reserve_price_cents=5_000_000
    )
    res = api.place_bid(
        listing["id"],
        create_bid_payload(5_199_999),
        make_buyer_headers(buyer_a["id"]),
    )
    validate_error(res, "ERR_BID_TOO_LOW")


def test_high_tier_bid_increment_five_hundred_thousand_cents(api):
    """PRD §3.3: "When the current maximum is at least the second-tier
    ceiling, the required increment is five thousand currency units (five
    hundred thousand cents)."

    Setup: ask=20_000_000; required increment = 500_000. Bid 20_500_000
    succeeds; 20_499_999 fails.
    """
    _, listing, _, buyer_a, _ = setup_auction_with_two_bidders(
        ask_price_cents=20_000_000, reserve_price_cents=20_000_000
    )
    bid = place_bid(buyer_a, listing, 20_500_000)
    assert bid["amount_cents"] == 20_500_000


def test_high_tier_one_below_increment_rejected(api):
    """PRD §3.3: "When the current maximum is at least the second-tier
    ceiling, the required increment is five thousand currency units (five
    hundred thousand cents)."
    PRD §3.3: "A bid below the required minimum is rejected with
    ERR_BID_TOO_LOW."

    Setup: ask=20_000_000 (high tier); required=20_500_000; bid 20_499_999 fails.
    """
    _, listing, _, buyer_a, _ = setup_auction_with_two_bidders(
        ask_price_cents=20_000_000, reserve_price_cents=20_000_000
    )
    res = api.place_bid(
        listing["id"],
        create_bid_payload(20_499_999),
        make_buyer_headers(buyer_a["id"]),
    )
    validate_error(res, "ERR_BID_TOO_LOW")


# ──────────────────────────────────────────────────────────
# §3.3 Deposit — 10% rounded up to next whole cent
# ──────────────────────────────────────────────────────────


def test_bid_deposit_is_ten_percent_rounded_up(api):
    """PRD §3.3: "computes its deposit_cents as ten percent of the bid amount
    rounded up to the next whole cent".

    Bid 1_050_001 → deposit = ceil(105_000.1) = 105_001.
    """
    _, listing, _, buyer_a, _ = setup_auction_with_two_bidders(
        ask_price_cents=1_000_000, reserve_price_cents=1_000_000
    )
    bid = place_bid(buyer_a, listing, 1_050_001)
    expected = math.ceil(1_050_001 * 0.10)
    assert bid["deposit_cents"] == expected


def test_bid_deposit_held_against_buyer(api):
    """PRD §3.3: "acquires the deposit hold against the buyer
    (Buyer.deposit_held_cents increases by the new deposit_cents)."
    """
    _, listing, _, buyer_a, _ = setup_auction_with_two_bidders(
        ask_price_cents=1_000_000, reserve_price_cents=1_000_000
    )
    bid = place_bid(buyer_a, listing, 1_050_000)
    refreshed = validate_success(
        api.get_buyer(buyer_a["id"], make_buyer_headers(buyer_a["id"])), 200
    )
    assert refreshed["deposit_held_cents"] == bid["deposit_cents"]
    assert refreshed["deposit_balance_cents"] == refreshed["deposit_held_cents"]


# ──────────────────────────────────────────────────────────
# §3.3 Outbid — previous LIVE → OUTBID, deposit released
# ──────────────────────────────────────────────────────────


def test_new_higher_bid_outbids_previous_and_releases_deposit(api):
    """PRD §3.3: "If a previous LIVE bid existed on the same listing, it is
    moved to OUTBID and its deposit hold is released."
    """
    _, listing, _, buyer_a, buyer_b = setup_auction_with_two_bidders(
        ask_price_cents=1_000_000, reserve_price_cents=1_000_000
    )
    bid_a = place_bid(buyer_a, listing, 1_050_000)
    bid_b = place_bid(buyer_b, listing, 1_250_000)

    # Buyer A's deposit must now be 0; B's must be the new bid's deposit.
    a_buyer = validate_success(
        api.get_buyer(buyer_a["id"], make_buyer_headers(buyer_a["id"])), 200
    )
    b_buyer = validate_success(
        api.get_buyer(buyer_b["id"], make_buyer_headers(buyer_b["id"])), 200
    )
    assert a_buyer["deposit_held_cents"] == 0
    assert b_buyer["deposit_held_cents"] == bid_b["deposit_cents"]


def test_listing_active_bid_id_advances_to_new_winner(api, admin_headers):
    """PRD §3.3: "The listing's active_bid_id is updated to the new bid's id."
    """
    _, listing, _, buyer_a, buyer_b = setup_auction_with_two_bidders(
        ask_price_cents=1_000_000, reserve_price_cents=1_000_000
    )
    place_bid(buyer_a, listing, 1_050_000)
    bid_b = place_bid(buyer_b, listing, 1_250_000)
    refreshed = validate_success(api.get_listing(listing["id"], admin_headers), 200)
    assert refreshed["active_bid_id"] == bid_b["id"]


# ──────────────────────────────────────────────────────────
# §3.3 Cancel
# ──────────────────────────────────────────────────────────


def test_cancel_live_bid_releases_deposit(api):
    """PRD §3.3: "A buyer may cancel their own LIVE bid before the auction
    closes; this transitions the bid from LIVE to CANCELLED and releases the
    deposit."
    """
    _, listing, _, buyer_a, _ = setup_auction_with_two_bidders(
        ask_price_cents=1_000_000, reserve_price_cents=1_000_000
    )
    bid = place_bid(buyer_a, listing, 1_050_000)
    cancelled = validate_success(
        api.cancel_bid(bid["id"], make_buyer_headers(buyer_a["id"])), 200
    )
    assert cancelled["status"] == "CANCELLED"
    refreshed_buyer = validate_success(
        api.get_buyer(buyer_a["id"], make_buyer_headers(buyer_a["id"])), 200
    )
    assert refreshed_buyer["deposit_held_cents"] == 0


# ──────────────────────────────────────────────────────────
# §3.3 Close auction
# ──────────────────────────────────────────────────────────


def test_close_auction_with_winning_bid_meets_reserve(api, admin_headers):
    """PRD §3.3: "if its amount_cents is at least the listing's
    reserve_price_cents, that bid is moved from LIVE to WON, every other LIVE
    bid for the listing is moved to LOST with deposit released, the listing
    transitions from ACTIVE to RESERVED, and a PurchaseOrder is created in
    PENDING_PAYMENT."
    """
    _, listing, _, buyer_a, _ = setup_auction_with_two_bidders(
        ask_price_cents=1_000_000, reserve_price_cents=1_000_000
    )
    place_bid(buyer_a, listing, 1_050_000)
    closed = validate_success(api.close_auction(listing["id"], admin_headers), 200)
    assert closed["status"] == "RESERVED"


def test_close_auction_with_no_bid_meeting_reserve_keeps_listing_active(api, admin_headers):
    """PRD §3.3: "If no LIVE bid meets the reserve, every LIVE bid is moved
    to LOST with deposit released and the listing remains in ACTIVE with no
    active_bid_id."
    """
    _, listing, _, buyer_a, _ = setup_auction_with_two_bidders(
        ask_price_cents=1_000_000, reserve_price_cents=10_000_000
    )
    # Bid only 1_050_000 — far below reserve 10_000_000.
    place_bid(buyer_a, listing, 1_050_000)
    closed = validate_success(api.close_auction(listing["id"], admin_headers), 200)
    assert closed["status"] == "ACTIVE"
    assert closed["active_bid_id"] is None
    refreshed_buyer = validate_success(
        api.get_buyer(buyer_a["id"], make_buyer_headers(buyer_a["id"])), 200
    )
    assert refreshed_buyer["deposit_held_cents"] == 0


# ──────────────────────────────────────────────────────────
# §3.7 Deposit limit
# ──────────────────────────────────────────────────────────


def test_bid_pushing_buyer_above_deposit_limit_rejected(api):
    """PRD §3.7: "Each buyer's deposit_held_cents (the running sum across all
    of their LIVE bids and their HOLDING reservation, which by invariant
    equals the buyer's deposit_balance_cents) must not exceed fifty million
    cents. A new bid or reservation that would push the total above this
    limit is rejected with ERR_DEPOSIT_LIMIT_EXCEEDED on placement."

    A bid of 600_000_000 cents (deposit ceil = 60_000_000) exceeds the
    50M limit on its own and must be rejected.
    """
    _, listing, _, buyer_a, _ = setup_auction_with_two_bidders(
        ask_price_cents=500_000_000, reserve_price_cents=500_000_000
    )
    res = api.place_bid(
        listing["id"],
        create_bid_payload(600_000_000),
        make_buyer_headers(buyer_a["id"]),
    )
    validate_error(res, "ERR_DEPOSIT_LIMIT_EXCEEDED")
