"""Bidding: reserve boundary, deposit/amount guards, OCC versioning, retraction."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    make_platform_admin_headers, make_buyer_headers,
    place_bid_payload, create_buyer, fund_buyer, set_clock,
    setup_funded_live_auction, setup_scheduled_auction, setup_live_auction,
    CLOCK_CLOSE,
)

ADMIN = make_platform_admin_headers()


def _closed_empty_auction(api):
    """A LIVE auction closed with zero bids (branch B), plus a funded buyer.
    Returns ctx with auc/fac_hdr/buyer_id/buyer_hdr/auc_version (open-time)."""
    ctx = setup_funded_live_auction(api)
    set_clock(api, CLOCK_CLOSE)
    validate_success(api.close_auction(ctx["auc"], ctx["fac_hdr"]))
    return ctx


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check / first_bid_at_reserve_boundary
# ---------------------------------------------------------------------------
def test_first_bid_exactly_at_reserve_is_accepted(api):
    """PRD §3.4: "Finally, the bid `amount_cents` must be at least the auction's
    `min_next_bid_cents`, else `ERR_BID_TOO_LOW`."
    PRD §3.4: "The auction's `min_next_bid_cents` is the `reserve_cents` whenever
    `high_bid_cents` is zero, and otherwise the `high_bid_cents` plus the
    `min_increment_cents`."

    Design: Difficulty/boundary_precision_check/first_bid_at_reserve_boundary
    """
    ctx = setup_funded_live_auction(api)  # reserve 50000, min_increment 5000, no bids
    resp = api.place_bid(ctx["auc"], place_bid_payload(ctx["buyer_id"], 50000, ctx["auc_version"]),
                         ctx["buyer_hdr"])
    bid = validate_success(resp, expected_status=201)
    assert bid["status"] == "ACTIVE"
    auction = validate_success(api.get_auction(ctx["auc"], ADMIN))
    assert auction["high_bid_cents"] == 50000
    assert auction["min_next_bid_cents"] == 55000


def test_first_bid_one_cent_below_reserve_is_rejected(api):
    """PRD §3.4: "Finally, the bid `amount_cents` must be at least the auction's
    `min_next_bid_cents`, else `ERR_BID_TOO_LOW`."

    Design: Difficulty/boundary_precision_check/first_bid_at_reserve_boundary
    """
    ctx = setup_funded_live_auction(api)  # min_next_bid_cents == reserve == 50000
    resp = api.place_bid(ctx["auc"], place_bid_payload(ctx["buyer_id"], 49999, ctx["auc_version"]),
                         ctx["buyer_hdr"])
    validate_error(resp, ApiErrorId.ERR_BID_TOO_LOW.value)


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict / bid_state_beats_fiscal
# ---------------------------------------------------------------------------
def test_bid_on_closed_auction_below_min_reports_not_live(api):
    """PRD §2.10: "For placing a bid, after the shared checks the order is: the
    auction must be live (`ERR_AUCTION_NOT_LIVE`), then the version must match
    (`ERR_STALE_VERSION`), then the buyer must not already hold the high bid
    (`ERR_ALREADY_HIGH_BIDDER`), then the buyer's available deposit must suffice
    (`ERR_INSUFFICIENT_DEPOSIT`), then the bid amount must clear the minimum
    (`ERR_BID_TOO_LOW`)."

    Design: Difficulty/priority_pair_validation_conflict/bid_state_beats_fiscal
    """
    ctx = _closed_empty_auction(api)
    resp = api.place_bid(ctx["auc"], place_bid_payload(ctx["buyer_id"], 40000, ctx["auc_version"]),
                         ctx["buyer_hdr"])
    validate_error(resp, ApiErrorId.ERR_AUCTION_NOT_LIVE.value)


def test_bid_on_closed_auction_far_below_min_reports_not_live(api):
    """PRD §3.4: "The auction must be `LIVE`; a bid on an auction in any other
    status is rejected with `ERR_AUCTION_NOT_LIVE`."

    Design: Difficulty/priority_pair_validation_conflict/bid_state_beats_fiscal
    """
    ctx = _closed_empty_auction(api)
    resp = api.place_bid(ctx["auc"], place_bid_payload(ctx["buyer_id"], 100, ctx["auc_version"]),
                         ctx["buyer_hdr"])
    validate_error(resp, ApiErrorId.ERR_AUCTION_NOT_LIVE.value)


# ---------------------------------------------------------------------------
# Corner: bidding guards, OCC, retraction
# ---------------------------------------------------------------------------
def test_retract_sole_high_bid_resets_auction(api):
    """PRD §3.4: "A buyer may retract one of its own bids, identified by its
    `bid_id`, while the bid is `ACTIVE` and the auction is `LIVE`, moving the bid to
    `RETRACTED`. If the retracted bid was the standing high bid, the auction
    re-selects its high bid over the remaining `ACTIVE` bids using the same selection
    rule; if no `ACTIVE` bids remain, `high_bid_cents` resets to zero and
    `high_bid_id` to null."

    Design: Corner/state_machines/retract_high_bid_resets_auction_high_bid
    """
    ctx = setup_funded_live_auction(api)
    bid = validate_success(api.place_bid(
        ctx["auc"], place_bid_payload(ctx["buyer_id"], 60000, ctx["auc_version"]),
        ctx["buyer_hdr"]), 201)
    retracted = validate_success(api.retract_bid(bid["id"], ctx["buyer_hdr"]))
    assert retracted["status"] == "RETRACTED"
    auction = validate_success(api.get_auction(ctx["auc"], ADMIN))
    assert auction["high_bid_cents"] == 0
    assert auction["min_next_bid_cents"] == 50000  # back to reserve


def test_bid_on_scheduled_auction_reports_not_live(api):
    """PRD §3.4: "The auction must be `LIVE`; a bid on an auction in any other
    status is rejected with `ERR_AUCTION_NOT_LIVE`."

    Design: Corner/validations/bid_on_scheduled_auction_returns_not_live
    """
    ctx = setup_scheduled_auction(api)  # SCHEDULED, never opened
    buyer = create_buyer(api)
    fund_buyer(api, buyer["id"], 100000)
    auction = validate_success(api.get_auction(ctx["auc"], ADMIN))
    resp = api.place_bid(ctx["auc"], place_bid_payload(buyer["id"], 60000, auction["version"]),
                         make_buyer_headers(buyer["id"]))
    validate_error(resp, ApiErrorId.ERR_AUCTION_NOT_LIVE.value)


def test_bid_below_reserve_reports_too_low(api):
    """PRD §3.4: "Finally, the bid `amount_cents` must be at least the auction's
    `min_next_bid_cents`, else `ERR_BID_TOO_LOW`."

    Design: Corner/validations/bid_below_reserve_returns_too_low
    """
    ctx = setup_funded_live_auction(api)
    resp = api.place_bid(ctx["auc"], place_bid_payload(ctx["buyer_id"], 49999, ctx["auc_version"]),
                         ctx["buyer_hdr"])
    validate_error(resp, ApiErrorId.ERR_BID_TOO_LOW.value)


def test_bid_with_insufficient_deposit_reports_402(api):
    """PRD §3.4: "The buyer's `deposit_available_cents` must be at least the required
    deposit of 20000 cents, else `ERR_INSUFFICIENT_DEPOSIT`."

    Design: Corner/validations/bid_insufficient_deposit_returns_402
    """
    ctx = setup_funded_live_auction(api, deposit=10000)  # below the 20000 requirement
    resp = api.place_bid(ctx["auc"], place_bid_payload(ctx["buyer_id"], 60000, ctx["auc_version"]),
                         ctx["buyer_hdr"])
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_DEPOSIT.value)


def test_high_bidder_second_bid_reports_already_high(api):
    """PRD §3.4: "A buyer who already holds the current high bid may not bid against
    itself, and such an attempt is rejected with `ERR_ALREADY_HIGH_BIDDER`."

    Design: Corner/validations/second_bid_by_high_bidder_returns_already_high
    """
    ctx = setup_funded_live_auction(api)
    validate_success(api.place_bid(
        ctx["auc"], place_bid_payload(ctx["buyer_id"], 50000, ctx["auc_version"]),
        ctx["buyer_hdr"]), 201)
    auction = validate_success(api.get_auction(ctx["auc"], ADMIN))
    resp = api.place_bid(ctx["auc"], place_bid_payload(ctx["buyer_id"], 60000, auction["version"]),
                         ctx["buyer_hdr"])
    validate_error(resp, ApiErrorId.ERR_ALREADY_HIGH_BIDDER.value)


def test_bid_with_stale_auction_version_reports_stale(api):
    """PRD §2.7: "If `expected_auction_version` does not equal the auction's current
    `version`, the create is rejected with `ERR_STALE_VERSION` and HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/bid_stale_auction_version_returns_412
    """
    ctx = setup_live_auction(api)
    buyer1 = create_buyer(api)
    buyer2 = create_buyer(api)
    fund_buyer(api, buyer1["id"], 100000)
    fund_buyer(api, buyer2["id"], 100000)
    # buyer1's accepted bid advances the auction version past `auc_version`.
    validate_success(api.place_bid(
        ctx["auc"], place_bid_payload(buyer1["id"], 60000, ctx["auc_version"]),
        make_buyer_headers(buyer1["id"])), 201)
    resp = api.place_bid(ctx["auc"], place_bid_payload(buyer2["id"], 65000, ctx["auc_version"]),
                         make_buyer_headers(buyer2["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_accepted_bid_increments_auction_version_by_one(api):
    """PRD §2.7: "Each accepted bid, each opening, and each closing increments the
    auction's `version`."

    Design: Corner/cross_cutting_complexity_layers/bid_increments_auction_version
    """
    ctx = setup_funded_live_auction(api)
    version_at_open = ctx["auc_version"]
    validate_success(api.place_bid(
        ctx["auc"], place_bid_payload(ctx["buyer_id"], 60000, version_at_open),
        ctx["buyer_hdr"]), 201)
    auction = validate_success(api.get_auction(ctx["auc"], ADMIN))
    assert auction["version"] == version_at_open + 1
