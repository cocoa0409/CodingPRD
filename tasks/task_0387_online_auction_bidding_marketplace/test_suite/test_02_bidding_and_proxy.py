"""Proxy bidding, bid increments, anti-sniping, auction close, retraction, self-trading.

Each test translates exactly one design-index instance. Difficulty instances each
receive at least two tests.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, make_seller_headers, make_buyer_headers,
    register_seller, register_buyer, register_seller_buyer,
    set_clock, advance_clock,
    setup_published_auction, setup_published_buy_now,
    create_and_publish_listing, place_bid,
)

ANON = TEST_USERS["anonymous_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ════════════════════════════════════════════════════════════════════
# Difficulty: proxy_bid_resolution_nested_min_branch (>=2 tests)
# ════════════════════════════════════════════════════════════════════

def test_proxy_incumbent_holds_nested_min(api):
    """PRD §3.3: "If the incoming bid's maximum is less than or equal to the previous
    winner's maximum, the incumbent holds: the previous winner stays the winner and its
    current_price_cents becomes the smaller of its own maximum and the incoming maximum
    plus one increment computed on the incoming maximum, while the incoming bid is recorded
    at its own maximum, marked OUTBID, with is_winning false."

    Design: Difficulty/combinatorial_formula/proxy_bid_resolution_nested_min_branch
    """
    seller, listing = setup_published_auction(
        start_price_cents=10000, scheduled_end_at="2026-06-10T00:00:00Z")
    a = register_buyer()
    b = register_buyer()
    bid_a = place_bid(listing["id"], a["id"], 30000)   # first -> 10000
    bid_b = place_bid(listing["id"], b["id"], 20000)   # incumbent holds at 20500

    after = validate_success(api.get_listing(listing["id"], ANON), 200)
    assert after["current_price_cents"] == 20500
    assert after["highest_bid_id"] == bid_a["id"]

    a_after = validate_success(api.get_bid(bid_a["id"], ANON), 200)
    b_after = validate_success(api.get_bid(bid_b["id"], ANON), 200)
    assert a_after["current_price_cents"] == 20500
    assert a_after["is_winning"] is True
    assert b_after["status"] == "OUTBID"


def test_proxy_new_bid_takes_lead_nested_min(api):
    """PRD §3.3: "If the incoming bid's maximum is strictly greater than the previous
    winner's maximum, the incoming bid takes the lead: its current_price_cents becomes the
    smaller of its own maximum and the previous winner's maximum plus one increment computed
    on that previous maximum, the previous winner keeps its committed price but is marked
    OUTBID with its is_winning set to false."

    Design: Difficulty/combinatorial_formula/proxy_bid_resolution_nested_min_branch
    """
    seller, listing = setup_published_auction(
        start_price_cents=10000, scheduled_end_at="2026-06-10T00:00:00Z")
    a = register_buyer()
    b = register_buyer()
    bid_a = place_bid(listing["id"], a["id"], 20000)   # first -> 10000
    # B max 50000 > A max 20000: B leads at min(50000, 20000 + increment(20000)=500) = 20500
    bid_b = place_bid(listing["id"], b["id"], 50000)

    after = validate_success(api.get_listing(listing["id"], ANON), 200)
    assert after["current_price_cents"] == 20500
    assert after["highest_bid_id"] == bid_b["id"]

    a_after = validate_success(api.get_bid(bid_a["id"], ANON), 200)
    b_after = validate_success(api.get_bid(bid_b["id"], ANON), 200)
    assert b_after["current_price_cents"] == 20500
    assert b_after["is_winning"] is True
    assert a_after["status"] == "OUTBID"


# ════════════════════════════════════════════════════════════════════
# Corner: proxy_tie_break_equal_max_incumbent_wins
# ════════════════════════════════════════════════════════════════════

def test_proxy_tie_break_equal_max_incumbent_wins(api):
    """PRD §3.3: "When the two maximums are exactly equal, the incumbent retains the lead
    by virtue of its earlier created_at, and the price is set to the shared maximum; the
    incoming bid is recorded OUTBID at its maximum."

    Design: Corner/calculations/proxy_tie_break_equal_max_incumbent_wins
    """
    seller, listing = setup_published_auction(
        start_price_cents=10000, scheduled_end_at="2026-06-10T00:00:00Z")
    a = register_buyer()
    b = register_buyer()
    bid_a = place_bid(listing["id"], a["id"], 20000)   # first
    bid_b = place_bid(listing["id"], b["id"], 20000)   # tie -> A wins at 20000

    after = validate_success(api.get_listing(listing["id"], ANON), 200)
    assert after["highest_bid_id"] == bid_a["id"]
    assert after["current_price_cents"] == 20000

    a_after = validate_success(api.get_bid(bid_a["id"], ANON), 200)
    b_after = validate_success(api.get_bid(bid_b["id"], ANON), 200)
    assert a_after["is_winning"] is True
    assert b_after["status"] == "OUTBID"


# ════════════════════════════════════════════════════════════════════
# Difficulty: bid_increment_minimum_exact_boundary (>=2 tests)
# ════════════════════════════════════════════════════════════════════

def test_bid_at_exact_minimum_increment_accepted(api):
    """PRD §3.3: "Every subsequent bid must have a max_proxy_cents of at least the listing's
    current current_price_cents plus the minimum increment computed on that current price."
    PRD §3.3: "For a price below 100 dollars (10000 cents) the increment is 1 dollar
    (100 cents). For a price from 100 dollars up to but not including 500 dollars
    (50000 cents) the increment is 5 dollars (500 cents)."

    Design: Difficulty/boundary_precision_check/bid_increment_minimum_exact_boundary
    """
    seller, listing = setup_published_auction(
        start_price_cents=10000, scheduled_end_at="2026-06-10T00:00:00Z")
    a = register_buyer()
    b = register_buyer()
    place_bid(listing["id"], a["id"], 10000)   # first -> current 10000, increment 500
    bid_b = place_bid(listing["id"], b["id"], 10500)   # exactly at minimum 10500

    b_after = validate_success(api.get_bid(bid_b["id"], ANON), 200)
    assert b_after["status"] == "ACCEPTED"
    assert b_after["is_winning"] is True
    after = validate_success(api.get_listing(listing["id"], ANON), 200)
    assert after["current_price_cents"] == 10500


def test_bid_one_below_minimum_increment_rejected(api):
    """PRD §3.3: "Every subsequent bid must have a max_proxy_cents of at least the listing's
    current current_price_cents plus the minimum increment computed on that current price.
    A bid that falls short is refused with ERR_BID_TOO_LOW."

    Design: Difficulty/boundary_precision_check/bid_increment_minimum_exact_boundary
    """
    seller, listing = setup_published_auction(
        start_price_cents=10000, scheduled_end_at="2026-06-10T00:00:00Z")
    a = register_buyer()
    b = register_buyer()
    place_bid(listing["id"], a["id"], 10000)   # current 10000, increment 500 -> min 10500
    res = api.create_bid(listing["id"],
                         {"bidder_account_id": b["id"], "max_proxy_cents": 10499},
                         make_buyer_headers(b["id"]))
    validate_error(res, "ERR_BID_TOO_LOW", expected_status=422)
    after = validate_success(api.get_listing(listing["id"], ANON), 200)
    assert after["current_price_cents"] == 10000


# ════════════════════════════════════════════════════════════════════
# Corner: bid_increment_tier_lower_edge_inclusive
# ════════════════════════════════════════════════════════════════════

def test_bid_increment_tier_lower_edge_inclusive(api):
    """PRD §3.3: "Each tier boundary belongs to the higher tier because the comparison is
    lower-edge inclusive: a price of exactly 50000 cents takes the 1000-cent increment,
    while 49999 cents takes the 500-cent increment."

    Design: Corner/calculations/bid_increment_tier_lower_edge_inclusive
    """
    seller, listing = setup_published_auction(
        start_price_cents=50000, scheduled_end_at="2026-06-10T00:00:00Z")
    a = register_buyer()
    b = register_buyer()
    place_bid(listing["id"], a["id"], 50000)   # current 50000, increment 1000 -> min 51000
    res = api.create_bid(listing["id"],
                         {"bidder_account_id": b["id"], "max_proxy_cents": 50999},
                         make_buyer_headers(b["id"]))
    validate_error(res, "ERR_BID_TOO_LOW", expected_status=422)
    after = validate_success(api.get_listing(listing["id"], ANON), 200)
    assert after["current_price_cents"] == 50000


# ════════════════════════════════════════════════════════════════════
# Difficulty: snipe_extension_window_edge (>=2 tests)
# ════════════════════════════════════════════════════════════════════

def test_snipe_extension_at_exact_trigger_edge(api):
    """PRD §3.4: "If that remaining time is at most the soft-close trigger of 5 minutes
    (300 seconds) and is still greater than zero, the system sets effective_end_at to the
    current clock plus the extension of 5 minutes (300 seconds); otherwise the end time is
    left unchanged. The boundary is inclusive: when exactly 300 seconds remain the extension
    fires, but when 301 seconds remain it does not."

    Design: Difficulty/boundary_precision_check/snipe_extension_window_edge
    """
    seller, listing = setup_published_auction(
        start_price_cents=10000, scheduled_end_at="2026-06-10T00:05:00Z",
        clock="2026-06-09T00:00:00Z")
    advance_clock("2026-06-10T00:00:00Z")   # remaining == 300s
    a = register_buyer()
    place_bid(listing["id"], a["id"], 10000)

    after = validate_success(api.get_listing(listing["id"], ANON), 200)
    assert after["effective_end_at"] == "2026-06-10T00:05:00.000Z"
    assert after["status"] == "ACTIVE"


def test_snipe_extension_window_does_not_stack(api):
    """PRD §3.4: "Each qualifying bid resets the window from the current clock — the new end
    is always the current clock plus 300 seconds, never a running sum, so successive late
    bids do not stack their extensions."

    Design: Difficulty/boundary_precision_check/snipe_extension_window_edge
    """
    seller, listing = setup_published_auction(
        start_price_cents=10000, scheduled_end_at="2026-06-10T00:05:00Z",
        clock="2026-06-09T00:00:00Z")
    advance_clock("2026-06-10T00:00:00Z")   # remaining 300 -> extend to 00:05:00
    a = register_buyer()
    place_bid(listing["id"], a["id"], 10000)
    first = validate_success(api.get_listing(listing["id"], ANON), 200)
    assert first["effective_end_at"] == "2026-06-10T00:05:00.000Z"

    # Second qualifying bid at clock 00:02:00 (remaining 180): end = clock + 300 = 00:07:00
    advance_clock("2026-06-10T00:02:00Z")
    b = register_buyer()
    place_bid(listing["id"], b["id"], 11000)
    second = validate_success(api.get_listing(listing["id"], ANON), 200)
    assert second["effective_end_at"] == "2026-06-10T00:07:00.000Z"


# ════════════════════════════════════════════════════════════════════
# Corner: snipe_no_extension_outside_window
# ════════════════════════════════════════════════════════════════════

def test_snipe_no_extension_outside_window(api):
    """PRD §3.4: "The boundary is inclusive: when exactly 300 seconds remain the extension
    fires, but when 301 seconds remain it does not."

    Design: Corner/calculations/snipe_no_extension_outside_window
    """
    seller, listing = setup_published_auction(
        start_price_cents=10000, scheduled_end_at="2026-06-10T00:05:01Z",
        clock="2026-06-09T00:00:00Z")
    advance_clock("2026-06-10T00:00:00Z")   # remaining == 301s
    a = register_buyer()
    place_bid(listing["id"], a["id"], 10000)

    after = validate_success(api.get_listing(listing["id"], ANON), 200)
    assert after["effective_end_at"] == "2026-06-10T00:05:01.000Z"


# ════════════════════════════════════════════════════════════════════
# Difficulty: auction_close_instant_boundary_inclusive (>=2 tests)
# ════════════════════════════════════════════════════════════════════

def test_bid_at_exact_close_instant_rejected(api):
    """PRD §3.3: "A bid placed once the current clock has reached the auction's
    effective_end_at, or on a terminal listing, is refused with ERR_AUCTION_CLOSED."

    Design: Difficulty/resource_temporal_overlap/auction_close_instant_boundary_inclusive
    """
    seller, listing = setup_published_auction(
        start_price_cents=10000, scheduled_end_at="2026-06-10T00:00:00Z")
    advance_clock("2026-06-10T00:00:00Z")   # exactly at close
    a = register_buyer()
    res = api.create_bid(listing["id"],
                         {"bidder_account_id": a["id"], "max_proxy_cents": 12000},
                         make_buyer_headers(a["id"]))
    validate_error(res, "ERR_AUCTION_CLOSED", expected_status=409)
    after = validate_success(api.get_listing(listing["id"], ANON), 200)
    assert after["status"] == "ENDED_NO_BIDS"


def test_auction_with_zero_bids_closes_no_bids(api):
    """PRD §3.6: "If the auction has zero bids at close, it moves to ENDED_NO_BIDS."

    Design: Difficulty/resource_temporal_overlap/auction_close_instant_boundary_inclusive
    """
    seller, listing = setup_published_auction(
        start_price_cents=10000, scheduled_end_at="2026-06-10T00:00:00Z")
    advance_clock("2026-06-10T00:00:00Z")
    after = validate_success(api.get_listing(listing["id"], ANON), 200)
    assert after["status"] == "ENDED_NO_BIDS"
    assert after["winner_account_id"] is None


# ════════════════════════════════════════════════════════════════════
# Corner: auction_close_reserve_not_met_no_order
# ════════════════════════════════════════════════════════════════════

def test_auction_close_reserve_not_met_no_order(api):
    """PRD §3.6: "If the auction has at least one bid but carries a non-null reserve that
    the highest bid's committed price fails to reach, the listing moves to
    ENDED_RESERVE_NOT_MET with no winner and no order."

    Design: Corner/state_machines/auction_close_reserve_not_met_no_order
    """
    seller, listing = setup_published_auction(
        start_price_cents=10000, reserve_price_cents=50000,
        scheduled_end_at="2026-06-10T00:00:00Z")
    a = register_buyer()
    place_bid(listing["id"], a["id"], 12000)   # below reserve 50000
    advance_clock("2026-06-10T00:00:01Z")

    after = validate_success(api.get_listing(listing["id"], ANON), 200)
    assert after["status"] == "ENDED_RESERVE_NOT_MET"
    assert after["winner_account_id"] is None


# ════════════════════════════════════════════════════════════════════
# Difficulty: self_trading_beats_bid_too_low (priority p9 > p11) (>=2)
# ════════════════════════════════════════════════════════════════════

def test_self_trading_beats_bid_too_low(api):
    """PRD §2.10: "Self-dealing comes ninth (ERR_SELF_TRADING). ... Bid eligibility comes
    eleventh (ERR_BID_TOO_LOW). ... A higher-priority failure always masks a lower-priority
    one."
    PRD §3.3: "The bidder must hold the BUYER role and must not be the listing's seller;
    a self-bid is refused with ERR_SELF_TRADING."

    Design: Difficulty/priority_pair_validation_conflict/self_trading_beats_bid_too_low
    """
    seller = register_seller_buyer()
    set_clock("2026-06-01T00:00:00Z")
    listing = create_and_publish_listing(
        seller["id"], format="AUCTION", start_price_cents=10000,
        scheduled_end_at="2026-06-10T00:00:00Z")
    # Self-bid (p9) AND below start_price (p11): must surface ERR_SELF_TRADING.
    res = api.create_bid(listing["id"],
                         {"bidder_account_id": seller["id"], "max_proxy_cents": 5000},
                         make_buyer_headers(seller["id"]))
    validate_error(res, "ERR_SELF_TRADING", expected_status=422)


def test_self_trading_reported_even_above_minimum(api):
    """PRD §3.3: "The bidder must hold the BUYER role and must not be the listing's seller;
    a self-bid is refused with ERR_SELF_TRADING."

    Design: Difficulty/priority_pair_validation_conflict/self_trading_beats_bid_too_low
    """
    seller = register_seller_buyer()
    set_clock("2026-06-01T00:00:00Z")
    listing = create_and_publish_listing(
        seller["id"], format="AUCTION", start_price_cents=10000,
        scheduled_end_at="2026-06-10T00:00:00Z")
    # Self-bid with an eligible amount (>= start_price): still ERR_SELF_TRADING.
    res = api.create_bid(listing["id"],
                         {"bidder_account_id": seller["id"], "max_proxy_cents": 20000},
                         make_buyer_headers(seller["id"]))
    validate_error(res, "ERR_SELF_TRADING", expected_status=422)


# ════════════════════════════════════════════════════════════════════
# Difficulty: auction_closed_beats_self_trading (p7 > p9) (>=2 tests)
# ════════════════════════════════════════════════════════════════════

def test_auction_closed_beats_self_trading(api):
    """PRD §2.10: "Auction-window timing comes seventh (ERR_AUCTION_CLOSED). ... Self-dealing
    comes ninth (ERR_SELF_TRADING). ... A higher-priority failure always masks a
    lower-priority one."

    Design: Difficulty/priority_pair_validation_conflict/auction_closed_beats_self_trading
    """
    seller = register_seller_buyer()
    set_clock("2026-06-01T00:00:00Z")
    listing = create_and_publish_listing(
        seller["id"], format="AUCTION", start_price_cents=10000,
        scheduled_end_at="2026-06-10T00:00:00Z")
    advance_clock("2026-06-10T00:00:01Z")   # auction closed (ENDED_NO_BIDS)
    # Self-bid (p9) on a closed auction (p7): must surface ERR_AUCTION_CLOSED.
    res = api.create_bid(listing["id"],
                         {"bidder_account_id": seller["id"], "max_proxy_cents": 5000},
                         make_buyer_headers(seller["id"]))
    validate_error(res, "ERR_AUCTION_CLOSED", expected_status=409)


def test_auction_closed_masks_self_trading_on_terminal_listing(api):
    """PRD §3.3: "A bid placed once the current clock has reached the auction's
    effective_end_at, or on a terminal listing, is refused with ERR_AUCTION_CLOSED."

    Design: Difficulty/priority_pair_validation_conflict/auction_closed_beats_self_trading
    """
    seller = register_seller_buyer()
    set_clock("2026-06-01T00:00:00Z")
    listing = create_and_publish_listing(
        seller["id"], format="AUCTION", start_price_cents=10000,
        scheduled_end_at="2026-06-10T00:00:00Z")
    advance_clock("2026-06-11T00:00:00Z")   # well past close, listing terminal
    res = api.create_bid(listing["id"],
                         {"bidder_account_id": seller["id"], "max_proxy_cents": 20000},
                         make_buyer_headers(seller["id"]))
    validate_error(res, "ERR_AUCTION_CLOSED", expected_status=409)


# ════════════════════════════════════════════════════════════════════
# Corner: bid_retract_inside_lockout_rejected
# ════════════════════════════════════════════════════════════════════

def test_bid_retract_inside_lockout_rejected(api):
    """PRD §3.3: "Retraction is allowed only when the current time is more than the lockout
    interval of 12 hours (43200 seconds) before the auction's effective_end_at; a retraction
    attempted inside that final 12-hour window, or against a bid that is currently winning,
    is refused with ERR_RETRACT_NOT_ALLOWED."

    Design: Corner/validations/bid_retract_inside_lockout_rejected
    """
    seller, listing = setup_published_auction(
        start_price_cents=10000, scheduled_end_at="2026-06-10T00:00:00Z")
    a = register_buyer()
    b = register_buyer()
    bid_a = place_bid(listing["id"], a["id"], 12000)
    place_bid(listing["id"], b["id"], 30000)   # A now OUTBID / non-winning
    advance_clock("2026-06-09T18:00:00Z")   # 6h before close -> inside lockout

    res = api.retract_bid(bid_a["id"], make_buyer_headers(a["id"]))
    validate_error(res, "ERR_RETRACT_NOT_ALLOWED", expected_status=422)
    a_after = validate_success(api.get_bid(bid_a["id"], ANON), 200)
    assert a_after["status"] == "OUTBID"


# ════════════════════════════════════════════════════════════════════
# Corner: self_trading_buy_now_rejected
# ════════════════════════════════════════════════════════════════════

def test_self_trading_buy_now_rejected(api):
    """PRD §3.6: "The buyer must hold the BUYER role, must not be the seller, and must have
    an ACTIVE account status."
    PRD §2.10: "Self-dealing comes ninth (ERR_SELF_TRADING)."

    Design: Corner/errors/self_trading_buy_now_rejected
    """
    seller = register_seller_buyer()
    set_clock("2026-06-01T00:00:00Z")
    listing = create_and_publish_listing(
        seller["id"], format="BUY_NOW", buy_now_price_cents=20000)
    res = api.buy_now(listing["id"], {"buyer_account_id": seller["id"], "shipping_cents": 0},
                      make_buyer_headers(seller["id"]))
    validate_error(res, "ERR_SELF_TRADING", expected_status=422)
