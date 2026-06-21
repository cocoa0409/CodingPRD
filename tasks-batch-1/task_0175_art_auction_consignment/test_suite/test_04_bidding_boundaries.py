"""Bidding thresholds: the minimum-next-bid increment bands (boundary
precision), the opening-bid floor, the empty-bid-set buy-in, channel
consistency, and the credit-limit guard.
"""
from test_helpers import validate_success, validate_error, get_success_data
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import (
    setup_open_lot, place_bid, AUCTIONEER,
)
from test_helpers.factories import FLAT_TIERS


# ===========================================================================
# Queue A — boundary_precision_check
# ===========================================================================
def test_min_next_bid_band_edge_rejects_below_accepts_at(api):
    """PRD §3.5: "a standing high of at least 1,000.00 and below 5,000.00
    (100000 up to but not including 500000 cents) requires 100.00 (10000
    cents)"
    PRD §3.5: "Band edges are half-open: a value exactly equal to a band's
    upper figure falls into the next band up."
    PRD §3.5: "A bid whose `amount_cents` is below the lot's minimum next bid
    ... is rejected with `ERR_BID_TOO_LOW`."

    With standing-high exactly 100000 the band is [100000,500000) so the
    increment is 10000 and min_next_bid is 110000: 109999 rejected, 110000
    accepted.

    Design: Difficulty/boundary_precision_check/boundary_bid_increment_band_edge
    """
    scene = setup_open_lot(tiers=FLAT_TIERS, reserve_cents=90000,
                           low_estimate_cents=120000, high_estimate_cents=200000)
    lot_id = scene["lot"]["id"]
    paddle_id = scene["paddle"]["id"]
    place_bid(lot_id, paddle_id, 100000)
    resp_low = api.create_bid(lot_id, {"paddle_registration_id": paddle_id,
                                       "amount_cents": 109999, "bid_channel": "FLOOR"}, AUCTIONEER)
    validate_error(resp_low, ApiErrorId.ERR_BID_TOO_LOW.value)
    ok = validate_success(
        api.create_bid(lot_id, {"paddle_registration_id": paddle_id,
                                "amount_cents": 110000, "bid_channel": "FLOOR"}, AUCTIONEER),
        expected_status=201)
    assert ok["amount_cents"] == 110000
    assert ok["status"] == "ACCEPTED"


def test_min_next_bid_above_edge_accepted(api):
    """PRD §3.5: "When there is a standing high, the minimum next bid is that
    standing high plus the increment for its band."
    PRD §3.5: "a standing high of at least 1,000.00 and below 5,000.00 (100000
    up to but not including 500000 cents) requires 100.00 (10000 cents)"

    X+1 case at the same band edge: a bid of 110001 (just above min_next_bid
    110000) is accepted.

    Design: Difficulty/boundary_precision_check/boundary_bid_increment_band_edge
    """
    scene = setup_open_lot(tiers=FLAT_TIERS, reserve_cents=90000,
                           low_estimate_cents=120000, high_estimate_cents=200000)
    lot_id = scene["lot"]["id"]
    paddle_id = scene["paddle"]["id"]
    place_bid(lot_id, paddle_id, 100000)
    ok = validate_success(
        api.create_bid(lot_id, {"paddle_registration_id": paddle_id,
                                "amount_cents": 110001, "bid_channel": "FLOOR"}, AUCTIONEER),
        expected_status=201)
    assert ok["amount_cents"] == 110001


def test_knock_down_empty_bid_set_buys_in(api):
    """PRD §3.5: "If instead no accepted bid exists, or the standing-high
    accepted bid is below the reserve, the lot is bought in: its `sale_status`
    moves from `OPEN` to `BOUGHT_IN`, its `hammer_price_cents` stays 0, no
    winning bid is set"

    Knocking down an OPEN lot with zero bids yields BOUGHT_IN, hammer 0.

    Design: Difficulty/boundary_precision_check/boundary_empty_bid_set_buy_in
    """
    scene = setup_open_lot(tiers=FLAT_TIERS, reserve_cents=1000000)
    lot_id = scene["lot"]["id"]
    lot = get_success_data(api.get_lot(lot_id, AUCTIONEER))
    knocked = get_success_data(api.knock_down_lot(
        lot_id, {"expected_lot_version": lot["version"]}, AUCTIONEER))
    assert knocked["sale_status"] == "BOUGHT_IN"
    assert knocked["hammer_price_cents"] == 0


def test_knock_down_empty_bid_set_sets_no_winner(api):
    """PRD §3.5: "the lot is bought in: its `sale_status` moves from `OPEN` to
    `BOUGHT_IN`, its `hammer_price_cents` stays 0, no winning bid is set, and
    the lot's `version` is incremented by 1."

    No winning paddle is recorded when the accepted-bid set is empty.

    Design: Difficulty/boundary_precision_check/boundary_empty_bid_set_buy_in
    """
    scene = setup_open_lot(tiers=FLAT_TIERS, reserve_cents=1000000)
    lot_id = scene["lot"]["id"]
    lot = get_success_data(api.get_lot(lot_id, AUCTIONEER))
    knocked = get_success_data(api.knock_down_lot(
        lot_id, {"expected_lot_version": lot["version"]}, AUCTIONEER))
    assert knocked["sale_status"] == "BOUGHT_IN"
    assert not knocked.get("winning_paddle_registration_id")


# ===========================================================================
# Queue B — calculations / validations / errors sections (bidding)
# ===========================================================================
def test_opening_bid_below_floor_rejected(api):
    """PRD §3.5: "When there is no standing high yet, the opening bid must be at
    least the starting floor of 50.00 (5000 cents). A bid whose `amount_cents`
    is ... below the opening floor for a first bid — is rejected with
    `ERR_BID_TOO_LOW`."

    Design: Corner/calculations/opening_bid_below_floor_rejected
    """
    scene = setup_open_lot(tiers=FLAT_TIERS, reserve_cents=0,
                           low_estimate_cents=100000, high_estimate_cents=200000)
    lot_id = scene["lot"]["id"]
    resp = api.create_bid(lot_id, {"paddle_registration_id": scene["paddle"]["id"],
                                   "amount_cents": 4999, "bid_channel": "FLOOR"}, AUCTIONEER)
    validate_error(resp, ApiErrorId.ERR_BID_TOO_LOW.value)


def test_bid_channel_mismatch_rejected(api):
    """PRD §3.5: "The channel of the individual bid must be consistent with the
    paddle's `registration_type` — a floor paddle bids on the floor channel, a
    phone paddle on the phone channel, an absentee paddle on the absentee
    channel — and a mismatch ... is rejected with `ERR_PADDLE_INELIGIBLE`."

    Design: Corner/validations/bid_channel_mismatch_rejected
    """
    scene = setup_open_lot(tiers=FLAT_TIERS, reserve_cents=0,
                           low_estimate_cents=100000, high_estimate_cents=200000)
    lot_id = scene["lot"]["id"]
    resp = api.create_bid(lot_id, {"paddle_registration_id": scene["paddle"]["id"],
                                   "amount_cents": 100000, "bid_channel": "PHONE"}, AUCTIONEER)
    validate_error(resp, ApiErrorId.ERR_PADDLE_INELIGIBLE.value)


def test_credit_limit_exceeded_on_bid(api):
    """PRD §3.5: "a bid, together with the projected `total_due_cents` it would
    generate if it went on to win, may not push the bidder's
    `outstanding_balance_cents` plus that projected total over the bidder's
    `credit_limit_cents`; exceeding it is rejected with
    `ERR_CREDIT_LIMIT_EXCEEDED`."

    Design: Corner/validations/credit_limit_exceeded_on_bid
    """
    scene = setup_open_lot(tiers=FLAT_TIERS, reserve_cents=1000000,
                           credit_limit_cents=1000000)
    lot_id = scene["lot"]["id"]
    resp = api.create_bid(lot_id, {"paddle_registration_id": scene["paddle"]["id"],
                                   "amount_cents": 1250000, "bid_channel": "FLOOR"}, AUCTIONEER)
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value)
