"""Bidding rules: tiered minimum increment, boundary precision, verified-buyer
gate, state-vs-increment precedence, OCC stale version, soft-close, and reads.
"""
from datetime import datetime

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID,
    operator_headers, anonymous_headers, make_buyer_headers,
    new_estate, new_registered_buyer, new_verified_buyer, new_listed_lot,
    lot_version, bid_on, create_bid_payload,
    setup_lot_with_high_bid, setup_sold_lot_extra_buyer,
)

OP = operator_headers()


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


# ==========================================================================
# Tiered minimum increment — step selected from a 4-band table
# ==========================================================================
class TestBidTieredIncrement:
    def test_bid_in_1000_band_below_min_rejected(self, api):
        """PRD §3.3: "for a current amount from 10000 up to but not including
        50000 cents the step is 1000 cents". PRD §3.3: "A bid below the minimum
        is rejected with ERR_BID_TOO_LOW (409)."

        Design: Difficulty/combinatorial_formula/bid_increment_tiered_step_selection
        """
        s = setup_lot_with_high_bid(api, starting_bid=10000, first_bid=10000)
        # current_bid 10000 -> band [10000,50000) -> step 1000 -> min_next 11000.
        v = lot_version(api, s["lot"]["id"])
        resp = api.create_bid(
            create_bid_payload(s["lot"]["id"], s["b2"]["id"], 10500, v),
            make_buyer_headers(s["b2"]["id"]))
        validate_error(resp, ApiErrorId.ERR_BID_TOO_LOW.value)
        lot = validate_success(api.get_lot(s["lot"]["id"], OP))
        assert lot["current_bid_cents"] == 10000
        assert lot["high_bidder_id"] == s["b1"]["id"]

    def test_bid_at_1000_band_minimum_accepted(self, api):
        """PRD §3.3: "for a current amount from 10000 up to but not including
        50000 cents the step is 1000 cents". PRD §3.3: "A bid is acceptable when
        its amount_cents is greater than or equal to this minimum next amount —
        an amount exactly equal to the minimum is valid."

        Design: Difficulty/combinatorial_formula/bid_increment_tiered_step_selection
        """
        s = setup_lot_with_high_bid(api, starting_bid=10000, first_bid=10000)
        # min_next == 10000 + 1000 == 11000; a bid of exactly 11000 is valid.
        bid_on(api, s["lot"]["id"], s["b2"]["id"], 11000)
        lot = validate_success(api.get_lot(s["lot"]["id"], OP))
        assert lot["current_bid_cents"] == 11000
        assert lot["high_bidder_id"] == s["b2"]["id"]


# ==========================================================================
# Boundary precision on the minimum-next amount (X-1 rejected, X accepted)
# ==========================================================================
class TestBidMinIncrementBoundary:
    def test_one_below_min_next_rejected(self, api):
        """PRD §3.3: "for a current amount below 2500 cents the step is 100
        cents". PRD §3.3: "A bid below the minimum is rejected with
        ERR_BID_TOO_LOW (409)."

        Design: Difficulty/boundary_precision_check/bid_min_increment_boundary
        """
        s = setup_lot_with_high_bid(api, starting_bid=2000, first_bid=2000)
        # current_bid 2000 -> step 100 -> min_next 2100; 2099 == min_next-1.
        v = lot_version(api, s["lot"]["id"])
        resp = api.create_bid(
            create_bid_payload(s["lot"]["id"], s["b2"]["id"], 2099, v),
            make_buyer_headers(s["b2"]["id"]))
        validate_error(resp, ApiErrorId.ERR_BID_TOO_LOW.value)
        lot = validate_success(api.get_lot(s["lot"]["id"], OP))
        assert lot["current_bid_cents"] == 2000

    def test_exactly_min_next_accepted(self, api):
        """PRD §3.3: "A bid is acceptable when its amount_cents is greater than
        or equal to this minimum next amount — an amount exactly equal to the
        minimum is valid."

        Design: Difficulty/boundary_precision_check/bid_min_increment_boundary
        """
        s = setup_lot_with_high_bid(api, starting_bid=2000, first_bid=2000)
        # min_next == 2000 + 100 == 2100; a bid of exactly 2100 is valid.
        bid_on(api, s["lot"]["id"], s["b2"]["id"], 2100)
        lot = validate_success(api.get_lot(s["lot"]["id"], OP))
        assert lot["current_bid_cents"] == 2100
        assert lot["high_bidder_id"] == s["b2"]["id"]


# ==========================================================================
# A bid requires a VERIFIED buyer (Bid transition depends on Buyer state)
# ==========================================================================
class TestBidRequiresVerifiedBuyer:
    def _live_lot_with_registered_buyer(self, api):
        estate = new_estate(api)
        buyer = new_registered_buyer(api, "B1", "b1@x.com")
        lot = new_listed_lot(api, estate["id"], starting_bid_cents=10000)
        validate_success(api.open_estate(estate["id"], OP))
        return estate, buyer, lot

    def test_registered_buyer_bid_rejected(self, api):
        """PRD §3.3: "The bidder must be VERIFIED; a still-REGISTERED bidder is
        rejected with ERR_BUYER_NOT_VERIFIED (409), and a SUSPENDED bidder with
        ERR_BUYER_SUSPENDED (409)."

        Design: Difficulty/cross_entity_state_dependency/bid_requires_verified_buyer
        """
        estate, buyer, lot = self._live_lot_with_registered_buyer(api)
        v = lot_version(api, lot["id"])
        resp = api.create_bid(
            create_bid_payload(lot["id"], buyer["id"], 10000, v),
            make_buyer_headers(buyer["id"]))
        validate_error(resp, ApiErrorId.ERR_BUYER_NOT_VERIFIED.value)
        lot_after = validate_success(api.get_lot(lot["id"], OP))
        assert lot_after["current_bid_cents"] == 0

    def test_verified_buyer_bid_accepted(self, api):
        """PRD §3.2: "An operator promotes a buyer from REGISTERED to VERIFIED;
        only a verified buyer may place bids."

        Design: Difficulty/cross_entity_state_dependency/bid_requires_verified_buyer
        """
        estate, buyer, lot = self._live_lot_with_registered_buyer(api)
        validate_success(api.verify_buyer(buyer["id"], OP))
        bid_on(api, lot["id"], buyer["id"], 10000)
        lot_after = validate_success(api.get_lot(lot["id"], OP))
        assert lot_after["current_bid_cents"] == 10000
        assert lot_after["high_bidder_id"] == buyer["id"]


# ==========================================================================
# Priority: state check (7, ERR_LOT_NOT_SELLING) outranks increment (13)
# ==========================================================================
class TestBidStateOutranksIncrement:
    def test_bid_on_sold_lot_returns_state_error(self, api):
        """PRD §3.3: "The bid names the lot via lot_id — which must be in
        SELLING, or the bid is rejected with ERR_LOT_NOT_SELLING (409)".
        PRD §2.10: "Earlier checks always mask later ones: a request that both
        lacks permission and carries a bad body returns the authorization error,
        not the validation error."

        Design: Difficulty/priority_pair_validation_conflict/bid_state_outranks_increment
        """
        s = setup_sold_lot_extra_buyer(api, first_bid=2000)
        # Lot is SOLD (state fails, priority 7) AND 100 is below min-next
        # (increment fails, priority 13); the state error must win.
        v = lot_version(api, s["lot"]["id"])
        resp = api.create_bid(
            create_bid_payload(s["lot"]["id"], s["b2"]["id"], 100, v),
            make_buyer_headers(s["b2"]["id"]))
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_SELLING.value)

    def test_rejected_late_bid_leaves_sale_intact(self, api):
        """PRD §3.4: "When a lot goes SELLING → SOLD, its hammer_price_cents is
        stamped to that high amount and its winning bid's is_winning is confirmed
        true; a passed lot keeps hammer_price_cents at null."

        Design: Difficulty/priority_pair_validation_conflict/bid_state_outranks_increment
        """
        s = setup_sold_lot_extra_buyer(api, first_bid=2000)
        v = lot_version(api, s["lot"]["id"])
        api.create_bid(create_bid_payload(s["lot"]["id"], s["b2"]["id"], 100, v),
                       make_buyer_headers(s["b2"]["id"]))
        lot = validate_success(api.get_lot(s["lot"]["id"], OP))
        assert lot["status"] == "SOLD"
        assert lot["current_bid_cents"] == 2000
        assert lot["hammer_price_cents"] == 2000
        assert lot["high_bidder_id"] == s["b1"]["id"]


# ==========================================================================
# OCC stale lot version on bid (corner)
# ==========================================================================
def test_stale_lot_version_bid_rejected(api):
    """PRD §2.7: "If expected_lot_version does not match the lot's current
    version at the moment the request is processed, the placement is rejected
    with ERR_STALE_VERSION (HTTP 412), preventing a client from bidding against
    a price it has not actually seen."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_lot_version_on_bid
    """
    estate = new_estate(api)
    b1 = new_verified_buyer(api, "B1", "b1@x.com")
    b2 = new_verified_buyer(api, "B2", "b2@x.com")
    lot = new_listed_lot(api, estate["id"], starting_bid_cents=2000)
    validate_success(api.open_estate(estate["id"], OP))
    lv0 = lot_version(api, lot["id"])
    # B1's accepted bid advances Lot.version past lv0.
    bid_on(api, lot["id"], b1["id"], 2000, version=lv0)
    # B2 still carries the pre-bid lv0 -> stale even though 2100 clears increment.
    resp = api.create_bid(
        create_bid_payload(lot["id"], b2["id"], 2100, lv0),
        make_buyer_headers(b2["id"]))
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
    lot_after = validate_success(api.get_lot(lot["id"], OP))
    assert lot_after["current_bid_cents"] == 2000
    assert lot_after["high_bidder_id"] == b1["id"]


# ==========================================================================
# Soft-close extension (corner)
# ==========================================================================
def test_bid_in_soft_close_window_extends_auction(api):
    """PRD §3.3: "When a bid is accepted while the logical clock reads at or
    after the moment soft_close_seconds before auction_ends_at and strictly
    before auction_ends_at, the estate's auction_ends_at is pushed forward by
    soft_close_seconds and its extended_count increases by one."

    Design: Corner/calculations/soft_close_extends_auction_end
    """
    estate = new_estate(api, auction_ends_at="2026-03-20T10:00:00Z",
                        soft_close_seconds=300)
    buyer = new_verified_buyer(api, "B1", "b1@x.com")
    lot = new_listed_lot(api, estate["id"], starting_bid_cents=1000)
    validate_success(api.open_estate(estate["id"], OP))
    validate_success(api.set_clock("2026-03-20T09:59:00Z", OP))  # inside 300s window
    original_end = _parse("2026-03-20T10:00:00Z")
    bid_on(api, lot["id"], buyer["id"], 1000)
    est = validate_success(api.get_estate(estate["id"], OP))
    assert est["extended_count"] == 1
    assert (_parse(est["auction_ends_at"]) - original_end).total_seconds() == 300


# ==========================================================================
# RBAC: bidding is Buyer-exclusive (corner)
# ==========================================================================
def test_operator_cannot_place_bid(api):
    """PRD §2.1: "When the headers are well-formed but the acting role is not
    permitted to perform the requested operation, the request is rejected with
    ERR_UNAUTHORIZED (HTTP 403)."

    Design: Corner/rbac/operator_cannot_place_bid
    """
    s = setup_lot_with_high_bid(api, starting_bid=1000, first_bid=1000)
    v = lot_version(api, s["lot"]["id"])
    resp = api.create_bid(
        create_bid_payload(s["lot"]["id"], s["b1"]["id"], 2000, v), OP)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


# ==========================================================================
# Reverse-reachability: bids filtered by buyer_id (corner)
# ==========================================================================
def test_bids_filtered_by_buyer(api):
    """PRD §2.9: "Filtered list paths take optional foreign-key query
    parameters — bids filtered by lot_id or buyer_id; orders filtered by
    estate_id, buyer_id, or pickup_window_id; disputes filtered by order_id or
    lot_id; donations filtered by lot_id or estate_id."

    Design: Corner/endpoints/bids_filtered_by_buyer
    """
    estate = new_estate(api)
    buyer = new_verified_buyer(api, "B1", "b1@x.com")
    lot = new_listed_lot(api, estate["id"], starting_bid_cents=1000)
    validate_success(api.open_estate(estate["id"], OP))
    bid_on(api, lot["id"], buyer["id"], 1000)
    data, meta = validate_paginated(api.list_bids(OP, params={"buyer_id": buyer["id"]}))
    assert len(data) == 1
    assert data[0]["buyer_id"] == buyer["id"]
