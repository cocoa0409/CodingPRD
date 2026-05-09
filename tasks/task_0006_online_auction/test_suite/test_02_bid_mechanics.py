"""Bid mechanics, the increment ladder, and soft-close (PRD §3.2)."""
import pytest

from test_helpers import (
    api_client, ApiErrorId, NON_EXISTENT_UUID,
    place_bid_payload, advance_clock_payload,
    TEST_USERS, make_seller_headers, make_bidder_headers,
    create_seller, create_bidder, create_lot_for_seller,
    create_and_publish_lot, advance_clock, get_lot, iso_future, iso_relative,
    setup_live_lot, place_bid_on_lot, publish_lot,
    validate_success, validate_error,
    assert_bid, assert_lot,
    deposit_required_cents, min_required_bid_cents, required_increment,
    DEPOSIT_MIN_CENTS, DEPOSIT_MAX_CENTS,
    SOFT_CLOSE_TRIGGER_SECONDS, SOFT_CLOSE_EXTENSION_SECONDS,
)


ADMIN = TEST_USERS["platform_admin_headers"]


class TestBidPlacement:
    def test_place_first_bid_at_starting_bid(self, api):
        """PRD §3.2: "When the lot's `bid_count` is zero the minimum-required-bid is
        simply `starting_bid_cents`..."

        Claim: First bid at exactly starting_bid_cents → 201 created.
        """
        seller, lot = setup_live_lot(starting_bid_cents=50_000, reserve_price_cents=100_000)
        bidder = create_bidder("Buyer", wallet_amount_cents=200_000)
        resp = api.place_bid(lot["id"], place_bid_payload(50_000), make_bidder_headers(bidder["id"]))
        bid = validate_success(resp, expected_status=201)
        assert_bid(bid)
        assert bid["amount_cents"] == 50_000
        assert bid["status"] in ("ACTIVE", "WINNING")

    def test_first_bid_below_starting_rejected(self, api):
        """PRD §3.2: "A submitted `amount_cents` less than the minimum-required-bid is
        rejected with `ERR_BID_BELOW_MIN_INCREMENT` (HTTP 422)."
        PRD §3.2: "When the lot's `bid_count` is zero the minimum-required-bid is simply
        `starting_bid_cents`..."

        Claim: First bid below starting_bid_cents → ERR_BID_BELOW_MIN_INCREMENT.
        """
        seller, lot = setup_live_lot(starting_bid_cents=50_000, reserve_price_cents=100_000)
        bidder = create_bidder("Buyer", wallet_amount_cents=200_000)
        resp = api.place_bid(lot["id"], place_bid_payload(49_999), make_bidder_headers(bidder["id"]))
        validate_error(resp, ApiErrorId.ERR_BID_BELOW_MIN_INCREMENT.value)

    def test_bid_on_non_live_lot_rejected(self, api):
        """PRD §3.2: "The lot must be in `LIVE` status: a bid attempt on a non-`LIVE`
        lot is rejected with `ERR_LOT_NOT_LIVE`."

        Claim: Bid on DRAFT lot → ERR_LOT_NOT_LIVE.
        """
        seller = create_seller()
        lot = create_lot_for_seller(seller)
        bidder = create_bidder("B1", wallet_amount_cents=200_000)
        resp = api.place_bid(lot["id"], place_bid_payload(60_000), make_bidder_headers(bidder["id"]))
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_LIVE.value)

    def test_bid_on_scheduled_lot_rejected(self, api):
        """PRD §3.2: "The lot must be in `LIVE` status: a bid attempt on a non-`LIVE`
        lot is rejected with `ERR_LOT_NOT_LIVE`."

        Claim: Bid on SCHEDULED lot → ERR_LOT_NOT_LIVE.
        """
        seller = create_seller()
        lot = create_and_publish_lot(seller)
        bidder = create_bidder("B1", wallet_amount_cents=200_000)
        resp = api.place_bid(lot["id"], place_bid_payload(60_000), make_bidder_headers(bidder["id"]))
        validate_error(resp, ApiErrorId.ERR_LOT_NOT_LIVE.value)


class TestIncrementLadder:
    @pytest.mark.parametrize("starting,first_bid,second_bid,second_bid_expected_ok", [
        # Tier 1: base in [0, 10000) -> increment 500
        (500, 500, 999, False),     # 500 + 500 = 1000 required, 999 too low
        (500, 500, 1000, True),     # exactly min
        # Tier 2 boundary cusp at base 10000: scaffold-difficulty test
        (9500, 9500, 9999, False),  # base 9500 → tier 1 (inc 500) → min 10000
        (9500, 9500, 10000, True),  # exactly 10000
    ])
    def test_increment_ladder_at_low_tiers(self, api, starting, first_bid, second_bid, second_bid_expected_ok):
        """PRD §3.2: "When the base is below 10000 cents (that is, below 100 dollars), the
        increment is 500 cents."
        PRD §3.2: "Tier lookup uses **strict less-than** against each tier's upper bound:
        a base price of exactly 10000 cents falls into the second tier (1000 cents step),
        not the first; a base of 9999 cents falls into the first tier (500 cents step)."

        Claim: tier-1 increment is 500; second bid below current+500 fails.
        """
        seller, lot = setup_live_lot(starting_bid_cents=starting, reserve_price_cents=200_000)
        bidder = create_bidder("B1", wallet_amount_cents=1_000_000)
        # First qualifying bid at exactly starting
        api.place_bid(lot["id"], place_bid_payload(first_bid), make_bidder_headers(bidder["id"]))
        # Second bid
        bidder2 = create_bidder("B2", wallet_amount_cents=1_000_000)
        resp = api.place_bid(lot["id"], place_bid_payload(second_bid), make_bidder_headers(bidder2["id"]))
        if second_bid_expected_ok:
            validate_success(resp, expected_status=201)
        else:
            validate_error(resp, ApiErrorId.ERR_BID_BELOW_MIN_INCREMENT.value)

    def test_tier_boundary_at_base_10000_strict_less_than(self, api):
        """PRD §3.2: "Tier lookup uses **strict less-than** against each tier's upper
        bound: a base price of exactly 10000 cents falls into the second tier (1000 cents
        step), not the first; a base of 9999 cents falls into the first tier (500 cents
        step)."

        Claim: When current_price_cents=10000, min_required_bid = 10000 + 1000 = 11000;
        bid 10999 rejected, bid 11000 accepted.

        # difficulty: boundary_precision_check/bid_increment_ladder_tier_boundary
        """
        seller, lot = setup_live_lot(starting_bid_cents=9500, reserve_price_cents=200_000)
        b0 = create_bidder("B0", wallet_amount_cents=1_000_000)
        b1 = create_bidder("B1", wallet_amount_cents=1_000_000)
        # Walk current_price to exactly 10000
        api.place_bid(lot["id"], place_bid_payload(9500), make_bidder_headers(b0["id"]))
        api.place_bid(lot["id"], place_bid_payload(10000), make_bidder_headers(b1["id"]))
        lot = get_lot(lot["id"])
        assert lot["current_price_cents"] == 10000

        # Test A: 10999 should reject (need 11000 = 10000 + tier-2 step 1000)
        b2 = create_bidder("B2", wallet_amount_cents=1_000_000)
        resp_a = api.place_bid(lot["id"], place_bid_payload(10999), make_bidder_headers(b2["id"]))
        validate_error(resp_a, ApiErrorId.ERR_BID_BELOW_MIN_INCREMENT.value)

        # Test B: 11000 should accept
        b3 = create_bidder("B3", wallet_amount_cents=1_000_000)
        resp_b = api.place_bid(lot["id"], place_bid_payload(11000), make_bidder_headers(b3["id"]))
        bid = validate_success(resp_b, expected_status=201)
        assert bid["amount_cents"] == 11000
        lot = get_lot(lot["id"])
        assert lot["current_price_cents"] == 11000

    def test_increment_at_base_100000_step_5000(self, api):
        """PRD §3.2: "When the base is at least 100000 cents and below 1000000 cents
        (between 1000 and 10000 dollars), the increment is 5000 cents."

        Claim: At base 100000, next min = 105000. Bid 104999 rejected.
        """
        seller, lot = setup_live_lot(starting_bid_cents=100_000, reserve_price_cents=200_000)
        b1 = create_bidder("B1", wallet_amount_cents=2_000_000)
        api.place_bid(lot["id"], place_bid_payload(100_000), make_bidder_headers(b1["id"]))
        b2 = create_bidder("B2", wallet_amount_cents=2_000_000)
        # base 100000 → tier-3 increment 5000 → min 105000
        resp = api.place_bid(lot["id"], place_bid_payload(104_999), make_bidder_headers(b2["id"]))
        validate_error(resp, ApiErrorId.ERR_BID_BELOW_MIN_INCREMENT.value)

        b3 = create_bidder("B3", wallet_amount_cents=2_000_000)
        resp_ok = api.place_bid(lot["id"], place_bid_payload(105_000), make_bidder_headers(b3["id"]))
        validate_success(resp_ok, expected_status=201)


class TestDepositHold:
    def test_deposit_required_clamped_to_min(self, api):
        """PRD §3.2: "the formula is the larger of 500 cents and the smaller of 1000000
        cents and the floor-truncated 10% of the reserve."

        Claim: When 10% of reserve < 500, deposit hold = 500; bidder needs ≥500 cents
        in wallet.
        """
        # reserve=4000 → 10% = 400 → clamped up to 500
        # set reserve=4000, starting=4000
        seller, lot = setup_live_lot(starting_bid_cents=4000, reserve_price_cents=4000)
        # bidder with wallet 499 — short by 1 cent of clamp-min 500
        bidder = create_bidder("Underfunded", wallet_amount_cents=499)
        resp = api.place_bid(lot["id"], place_bid_payload(4000), make_bidder_headers(bidder["id"]))
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_DEPOSIT_FUNDS.value)

        # And same lot with wallet 500 — passes
        bidder2 = create_bidder("Funded", wallet_amount_cents=500)
        resp_ok = api.place_bid(lot["id"], place_bid_payload(4000), make_bidder_headers(bidder2["id"]))
        validate_success(resp_ok, expected_status=201)

    def test_insufficient_deposit_funds(self, api):
        """PRD §3.2: "A funding gap produces `ERR_INSUFFICIENT_DEPOSIT_FUNDS` (HTTP 402)."

        Claim: wallet < deposit_required → ERR_INSUFFICIENT_DEPOSIT_FUNDS at HTTP 402.
        """
        seller, lot = setup_live_lot(reserve_price_cents=100_000, starting_bid_cents=50_000)
        # Required deposit = max(500, min(1_000_000, floor(100_000 * 0.10))) = 10_000
        bidder = create_bidder("Tight", wallet_amount_cents=9_999)
        resp = api.place_bid(lot["id"], place_bid_payload(50_000), make_bidder_headers(bidder["id"]))
        assert resp.status_code == 402
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_INSUFFICIENT_DEPOSIT_FUNDS"

    def test_deposit_aggregate_capacity_across_lots(self, api):
        """PRD §3.2: "The fiscal precondition (priority 13) is that the bidder's
        `wallet_balance_cents` minus their existing `held_deposit_cents` is at least the
        new required deposit; on a lot for which the bidder already holds a `HELD`
        `Deposit`, no second deposit is calculated and no funds are re-checked."
        PRD §5: ERR_INSUFFICIENT_DEPOSIT_FUNDS is HTTP 402.

        Claim: With wallet=15000 and one HELD 10000 deposit, second lot requiring 10000
        deposit → ERR_INSUFFICIENT_DEPOSIT_FUNDS (15000 - 10000 = 5000 < 10000 required).

        # difficulty: resource_temporal_overlap/deposit_aggregate_capacity_overlap
        """
        # Both lots must be LIVE simultaneously. The default fixture's clock-advance
        # would close lot_x before lot_y becomes LIVE, so build both with long
        # overlapping windows and advance the clock once.
        seller_a = create_seller("S-A")
        seller_b = create_seller("S-B")
        T = 3600
        WIN = 30 * 24 * 3600  # 30 days, well past any per-test advance
        lot_x_draft = create_lot_for_seller(
            seller_a,
            reserve_price_cents=100_000,
            starting_bid_cents=50_000,
            scheduled_start_at=iso_relative(T),
            scheduled_end_at=iso_relative(T + WIN),
        )
        lot_y_draft = create_lot_for_seller(
            seller_b,
            reserve_price_cents=100_000,
            starting_bid_cents=50_000,
            scheduled_start_at=iso_relative(T),
            scheduled_end_at=iso_relative(T + WIN),
        )
        publish_lot(lot_x_draft, seller_a)
        publish_lot(lot_y_draft, seller_b)
        # Cross both starts in a single advance
        advance_clock(T + 60)
        lot_x = get_lot(lot_x_draft["id"])
        lot_y = get_lot(lot_y_draft["id"])
        assert lot_x["status"] == "LIVE", f"lot_x status {lot_x['status']!r}"
        assert lot_y["status"] == "LIVE", f"lot_y status {lot_y['status']!r}"

        bidder = create_bidder("Constrained", wallet_amount_cents=15_000)

        # Bid on lot_x first → Deposit 10000 HELD; held_deposit_cents=10000
        first = api.place_bid(lot_x["id"], place_bid_payload(50_000), make_bidder_headers(bidder["id"]))
        validate_success(first, expected_status=201)

        # Bid on lot_y → would require new deposit 10000; 15000 - 10000 = 5000 < 10000
        resp = api.place_bid(lot_y["id"], place_bid_payload(50_000), make_bidder_headers(bidder["id"]))
        assert resp.status_code == 402
        body = resp.json()
        assert body["data"]["error_id"] == "ERR_INSUFFICIENT_DEPOSIT_FUNDS"

    def test_subsequent_bids_same_lot_reuse_deposit(self, api):
        """PRD §3.2: "Subsequent bids by the same bidder on the same lot reuse the same
        `Deposit`."

        Claim: Same bidder bidding twice on same lot does not consume more wallet capacity.
        """
        seller, lot = setup_live_lot(reserve_price_cents=100_000, starting_bid_cents=50_000)
        bidder = create_bidder("BidderRepeat", wallet_amount_cents=15_000)
        # First bid creates Deposit (10000 HELD). wallet should remain enough for repeat.
        api.place_bid(lot["id"], place_bid_payload(50_000), make_bidder_headers(bidder["id"]))

        # Place a higher second bid — no new deposit. Increment from base 50000 (tier 2, step 1000) → 51000
        resp = api.place_bid(lot["id"], place_bid_payload(51_000), make_bidder_headers(bidder["id"]))
        validate_success(resp, expected_status=201)


class TestSoftClose:
    def test_bid_listing_sort_by_placed_at_desc(self, api):
        """PRD §3.2: "The per-lot bid listing returns bids sorted by `placed_at`
        descending (most recent first); it does not redact the `bidder_id` of any bid."

        Claim: GET /lots/{id}/bids returns bids in placed_at DESC order.
        """
        seller, lot = setup_live_lot(starting_bid_cents=50_000, reserve_price_cents=200_000)
        b1 = create_bidder("Earlier", wallet_amount_cents=200_000)
        b2 = create_bidder("Later", wallet_amount_cents=200_000)
        api.place_bid(lot["id"], place_bid_payload(50_000), make_bidder_headers(b1["id"]))
        api.place_bid(lot["id"], place_bid_payload(51_000), make_bidder_headers(b2["id"]))
        resp = api.list_bids(lot["id"], TEST_USERS["bidder_headers"])
        body = resp.json()
        assert resp.status_code == 200
        bids = body["data"]
        assert len(bids) == 2
        assert bids[0]["placed_at"] >= bids[1]["placed_at"]
