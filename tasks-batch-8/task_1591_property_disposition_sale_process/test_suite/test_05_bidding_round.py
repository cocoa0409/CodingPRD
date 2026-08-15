"""The bidding round: business-screen ordering on submission, best-and-final
improvement, selection cascade, entity-backed Buyer ownership, and the deposit
floor."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    close_offers,
    create_bid_payload,
    make_buyer_headers,
    pipeline_through_offers,
    pipeline_to_bid,
    place_bid,
    register_bidder,
    register_qualified_bidder,
    set_clock,
    validate_error,
    validate_success,
)

DM = TEST_USERS["dm_headers"]


class TestSubmissionScreenOrdering:
    def test_bid_create_offers_closed_state_error_wins(self, api):
        """PRD: "Beyond shape and ownership, four business screens apply in a
        fixed order: the asset's `marketing_status` must be `OFFERS_OPEN`
        (`ERR_OFFERS_NOT_OPEN`), the clock must be at or before
        `offers_deadline` (`ERR_OFFERS_DEADLINE_PASSED`), the bidder must be
        `QUALIFIED` (`ERR_BIDDER_NOT_QUALIFIED`), and the proposed
        `deposit_cents` must meet the deposit floor"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_bid_create
        """
        ws = pipeline_through_offers()
        bidder = register_qualified_bidder(ws["asset"]["id"], 1_500_000_000)
        # Advance past the deadline AND close the round: both the state screen
        # and the temporal screen are violated; the state screen is first.
        set_clock("2026-09-16T00:00:00Z")
        close_offers(ws["asset"]["id"])
        payload = create_bid_payload(ws["asset"]["id"], bidder["id"],
                                     5_000_000_000, 150_000_000)
        validate_error(api.create_bid(payload, make_buyer_headers(bidder["id"])),
                       ApiErrorId.ERR_OFFERS_NOT_OPEN)

    def test_bid_create_offers_closed_isolated_state_error(self, api):
        """PRD: "Beyond shape and ownership, four business screens apply in a
        fixed order: the asset's `marketing_status` must be `OFFERS_OPEN`
        (`ERR_OFFERS_NOT_OPEN`)"
        PRD: "Closing the round moves `OFFERS_OPEN` to `OFFERS_CLOSED` and is
        itself time-gated: the clock must be at or after `offers_deadline`"

        Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_bid_create
        """
        ws = pipeline_through_offers()
        bidder = register_qualified_bidder(ws["asset"]["id"], 1_500_000_000)
        # Close at exactly the deadline: the temporal screen is satisfied
        # (clock is at, not after, the deadline), isolating the state screen.
        set_clock("2026-09-15T00:00:00Z")
        close_offers(ws["asset"]["id"])
        payload = create_bid_payload(ws["asset"]["id"], bidder["id"],
                                     5_000_000_000, 150_000_000)
        validate_error(api.create_bid(payload, make_buyer_headers(bidder["id"])),
                       ApiErrorId.ERR_OFFERS_NOT_OPEN)

    def test_bid_create_pending_bidder_referential_wins(self, api):
        """PRD: "Beyond shape and ownership, four business screens apply in a
        fixed order: the asset's `marketing_status` must be `OFFERS_OPEN`
        (`ERR_OFFERS_NOT_OPEN`), the clock must be at or before
        `offers_deadline` (`ERR_OFFERS_DEADLINE_PASSED`), the bidder must be
        `QUALIFIED` (`ERR_BIDDER_NOT_QUALIFIED`), and the proposed
        `deposit_cents` must meet the deposit floor — at least the greater of
        three percent of the offered price, rounded half up, and 10,000,000
        cents (`ERR_DEPOSIT_BELOW_MINIMUM`, HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_bid_create
        """
        ws = pipeline_through_offers()
        bidder = register_bidder(ws["asset"]["id"], 1_500_000_000)  # stays PENDING
        # Both the qualification screen and the deposit floor are violated;
        # qualification is earlier in the fixed order.
        payload = create_bid_payload(ws["asset"]["id"], bidder["id"],
                                     5_000_000_000, 1)
        validate_error(api.create_bid(payload, make_buyer_headers(bidder["id"])),
                       ApiErrorId.ERR_BIDDER_NOT_QUALIFIED)

    def test_bid_create_low_deposit_fiscal_isolated(self, api):
        """PRD: "the proposed `deposit_cents` must meet the deposit floor — at
        least the greater of three percent of the offered price, rounded half
        up, and 10,000,000 cents (`ERR_DEPOSIT_BELOW_MINIMUM`, HTTP 422)."

        Design: Difficulty/priority_pair_validation_conflict/referential_beats_fiscal_on_bid_create
        """
        ws = pipeline_through_offers()
        bidder = register_qualified_bidder(ws["asset"]["id"], 1_500_000_000)
        # Only the deposit floor is violated: the fiscal screen fires alone.
        payload = create_bid_payload(ws["asset"]["id"], bidder["id"],
                                     5_000_000_000, 1)
        validate_error(api.create_bid(payload, make_buyer_headers(bidder["id"])),
                       ApiErrorId.ERR_DEPOSIT_BELOW_MINIMUM)

    def test_bid_create_past_deadline_temporal_wins(self, api):
        """PRD: "Beyond shape and ownership, four business screens apply in a
        fixed order: the asset's `marketing_status` must be `OFFERS_OPEN`
        (`ERR_OFFERS_NOT_OPEN`), the clock must be at or before
        `offers_deadline` (`ERR_OFFERS_DEADLINE_PASSED`), the bidder must be
        `QUALIFIED` (`ERR_BIDDER_NOT_QUALIFIED`), and the proposed
        `deposit_cents` must meet the deposit floor"

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_bid_create
        """
        ws = pipeline_through_offers()
        bidder = register_qualified_bidder(ws["asset"]["id"], 1_500_000_000)
        # Round still OFFERS_OPEN but the clock is past the deadline, and the
        # deposit is below the floor: the temporal screen precedes the fiscal.
        set_clock("2026-09-16T00:00:00Z")
        payload = create_bid_payload(ws["asset"]["id"], bidder["id"],
                                     5_000_000_000, 1)
        validate_error(api.create_bid(payload, make_buyer_headers(bidder["id"])),
                       ApiErrorId.ERR_OFFERS_DEADLINE_PASSED)

    def test_bid_create_past_deadline_sufficient_deposit(self, api):
        """PRD: "the clock must be at or before `offers_deadline`
        (`ERR_OFFERS_DEADLINE_PASSED`)"

        Design: Difficulty/priority_pair_validation_conflict/temporal_beats_fiscal_on_bid_create
        """
        ws = pipeline_through_offers()
        bidder = register_qualified_bidder(ws["asset"]["id"], 1_500_000_000)
        set_clock("2026-09-16T00:00:00Z")
        # Sufficient deposit: only the temporal screen can fire.
        payload = create_bid_payload(ws["asset"]["id"], bidder["id"],
                                     5_000_000_000, 150_000_000)
        validate_error(api.create_bid(payload, make_buyer_headers(bidder["id"])),
                       ApiErrorId.ERR_OFFERS_DEADLINE_PASSED)


class TestImprovement:
    def test_bid_improve_requires_strictly_greater_price(self, api):
        """PRD: "the new `price_cents` must be strictly greater than the bid's
        current price — an equal or lower figure is rejected with
        `ERR_BID_IMPROVEMENT_TOO_LOW` (HTTP 422). A successful improvement
        replaces `price_cents` and increments `improvement_count` by one,
        leaving the bid in `SUBMITTED`."

        Design: Corner/state_machines/bid_improve_requires_strictly_greater_price
        """
        ws = pipeline_to_bid()
        bid, headers = ws["bid"], ws["buyer_headers"]

        validate_error(api.improve_bid(bid["id"], 5_000_000_000, headers),
                       ApiErrorId.ERR_BID_IMPROVEMENT_TOO_LOW)

        improved = validate_success(
            api.improve_bid(bid["id"], 5_000_000_001, headers))
        assert improved["price_cents"] == 5_000_000_001
        assert improved["improvement_count"] == 1
        assert improved["status"] == "SUBMITTED"


class TestSelectionCascade:
    def test_bid_select_cascades_rejections_count_conserved(self, api):
        """PRD: "Selection is exclusive by cascade — every other bid of the same
        asset still sitting in `SUBMITTED` or `SHORTLISTED` is moved to
        `REJECTED` in the same request."
        PRD: "Unless otherwise specified, all list endpoints return resources
        sorted by their creation timestamp in ascending order."

        Design: Corner/state_machines/bid_select_cascades_rejections_count_conserved
        """
        ws = pipeline_through_offers()
        bidders = [
            register_qualified_bidder(ws["asset"]["id"], 1_500_000_000, f"B{i}")
            for i in (1, 2, 3)
        ]
        bids = [
            place_bid(ws["asset"]["id"], b["id"], price, 150_000_000)
            for b, price in zip(bidders, (5_000_000_000, 4_900_000_000,
                                          4_800_000_000))
        ]
        set_clock("2026-09-16T00:00:00Z")
        close_offers(ws["asset"]["id"])
        validate_success(api.shortlist_bid(bids[0]["id"], DM))
        validate_success(api.shortlist_bid(bids[1]["id"], DM))
        # bids[2] deliberately left SUBMITTED.

        selected = validate_success(api.select_bid(bids[0]["id"], DM))
        assert selected["status"] == "SELECTED"

        listed = validate_success(api.list_asset_bids(ws["asset"]["id"], DM))
        assert len(listed) == 3, "no bid is deleted by the cascade"
        statuses = [b["status"] for b in listed]
        assert statuses == ["SELECTED", "REJECTED", "REJECTED"], (
            f"creation order bid1 SELECTED, bid2 (SHORTLISTED) REJECTED, "
            f"bid3 (SUBMITTED) REJECTED; got {statuses}")


class TestOwnershipAndDepositFloor:
    def test_rbac_buyer_entity_backed_ownership(self, api):
        """PRD: "The submission payload names the `asset_id` and the
        `bidder_id` — which must equal the caller's `X-User-ID`, since a buyer
        acts strictly as its own bidder entity, with mismatches rejected as
        `ERR_FORBIDDEN_ROLE`"

        Design: Corner/rbac/rbac_buyer_entity_backed_ownership
        """
        ws = pipeline_through_offers()
        b1 = register_qualified_bidder(ws["asset"]["id"], 1_500_000_000, "B1")
        b2 = register_qualified_bidder(ws["asset"]["id"], 1_500_000_000, "B2")
        # Caller acts as bidder b1 but names bidder b2 in the payload.
        payload = create_bid_payload(ws["asset"]["id"], b2["id"],
                                     5_000_000_000, 150_000_000)
        validate_error(api.create_bid(payload, make_buyer_headers(b1["id"])),
                       ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_err_deposit_below_minimum_boundary(self, api):
        """PRD: "the proposed `deposit_cents` must meet the deposit floor — at
        least the greater of three percent of the offered price, rounded half
        up, and 10,000,000 cents (`ERR_DEPOSIT_BELOW_MINIMUM`, HTTP 422)."
        PRD: "A clean submission enters in `SUBMITTED` status with
        `improvement_count` at 0."

        Design: Corner/errors/err_deposit_below_minimum_boundary
        """
        ws = pipeline_through_offers()
        bidder = register_qualified_bidder(ws["asset"]["id"], 1_500_000_000)
        headers = make_buyer_headers(bidder["id"])
        # 3% of the 5,000,000,000 price is 150,000,000; one cent below fails.
        payload = create_bid_payload(ws["asset"]["id"], bidder["id"],
                                     5_000_000_000, 149_999_999)
        validate_error(api.create_bid(payload, headers),
                       ApiErrorId.ERR_DEPOSIT_BELOW_MINIMUM)

        ok = create_bid_payload(ws["asset"]["id"], bidder["id"],
                                5_000_000_000, 150_000_000)
        bid = validate_success(api.create_bid(ok, headers), 201)
        assert bid["status"] == "SUBMITTED"
        assert bid["improvement_count"] == 0
