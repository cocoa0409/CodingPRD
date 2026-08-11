"""Bidding: minimum-bid boundary and increment rule, retraction, auction-state
gating, temporal-vs-fiscal priority, and bid OCC (PRD §2.6, §2.9, §3.7)."""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    set_clock,
    register_owner,
    setup_unclaimed_intake,
    setup_open_auction,
    create_auction_for_intake,
    place_bid,
    get_auction_version,
    create_bid_payload,
    owner_headers,
)

REGISTRAR = TEST_USERS["registrar_headers"]


class TestMinimumBidBoundary:
    def test_bid_exactly_at_minimum_accepted(self, api):
        """PRD §3.7: "When no `ACTIVE` bid exists on the auction, the minimum is
        the `reserve_price_cents`."
        PRD §3.7: "Acceptance is inclusive: a bid exactly equal to the minimum is
        accepted, while one cent below it is rejected with `ERR_BID_BELOW_MINIMUM`
        (HTTP 422)."

        Reserve is 20000 (appraised 100000): 19999 rejected, 20000 accepted.

        Design: Difficulty/boundary_precision_check/bid_exactly_at_minimum_accepted
        """
        scenario = setup_open_auction(serial="MIN100", appraised_value_cents=100000)
        assert scenario["auction"]["reserve_price_cents"] == 20000
        bidder = register_owner("o1@x.com", "O One")
        version = scenario["auction_version"]
        resp = api.place_bid(
            scenario["auction"]["id"],
            create_bid_payload(19999, version),
            owner_headers(bidder),
        )
        validate_error(resp, ApiErrorId.ERR_BID_BELOW_MINIMUM, expected_status=422)
        accepted = validate_success(
            api.place_bid(
                scenario["auction"]["id"],
                create_bid_payload(20000, version),
                owner_headers(bidder),
            ),
            expected_status=201,
        )
        assert accepted["amount_cents"] == 20000
        assert accepted["status"] == "ACTIVE"

    def test_bid_at_reserve_floor_accepted(self, api):
        """PRD §3.7: "The `reserve_price_cents` is the larger of 1000 cents and
        twenty percent of the intake's `appraised_value_cents` rounded half-up."
        PRD §3.7: "Acceptance is inclusive: a bid exactly equal to the minimum is
        accepted, while one cent below it is rejected with `ERR_BID_BELOW_MINIMUM`
        (HTTP 422)."

        Appraised 4000 floors the reserve at 1000: 999 rejected, 1000 accepted.

        Design: Difficulty/boundary_precision_check/bid_exactly_at_minimum_accepted
        """
        scenario = setup_open_auction(serial="MIN101", appraised_value_cents=4000)
        assert scenario["auction"]["reserve_price_cents"] == 1000, (
            f"reserve must floor at 1000, got {scenario['auction']['reserve_price_cents']}"
        )
        bidder = register_owner("o1@x.com", "O One")
        version = scenario["auction_version"]
        resp = api.place_bid(
            scenario["auction"]["id"], create_bid_payload(999, version),
            owner_headers(bidder),
        )
        validate_error(resp, ApiErrorId.ERR_BID_BELOW_MINIMUM, expected_status=422)
        accepted = validate_success(
            api.place_bid(
                scenario["auction"]["id"], create_bid_payload(1000, version),
                owner_headers(bidder),
            ),
            expected_status=201,
        )
        assert accepted["amount_cents"] == 1000
        assert accepted["status"] == "ACTIVE"

    def test_next_minimum_bid_increment_rule(self, api):
        """PRD §3.7: "Otherwise the leading amount is the highest `amount_cents`
        among `ACTIVE` bids, the increment is the larger of 500 cents and five
        percent of that leading amount rounded half-up, and the minimum is the
        leading amount plus the increment."
        PRD §3.7: "Lower earlier bids are not displaced at placement time —
        multiple `ACTIVE` bids coexist until close."

        Leading 20000 -> increment max(500, 1000) == 1000 -> minimum 21000:
        20999 rejected, 21000 accepted, and the 20000 bid stays ACTIVE.

        Design: Corner/calculations/next_minimum_bid_increment_rule
        """
        scenario = setup_open_auction(serial="INC100", appraised_value_cents=100000)
        bidder1 = register_owner("o1@x.com", "O One")
        bidder2 = register_owner("o2@x.com", "O Two")
        first = place_bid(
            scenario["auction"]["id"], bidder1, 20000, scenario["auction_version"]
        )
        live_version = get_auction_version(scenario["auction"]["id"])
        resp = api.place_bid(
            scenario["auction"]["id"],
            create_bid_payload(20999, live_version),
            owner_headers(bidder2),
        )
        validate_error(resp, ApiErrorId.ERR_BID_BELOW_MINIMUM, expected_status=422)
        accepted = validate_success(
            api.place_bid(
                scenario["auction"]["id"],
                create_bid_payload(21000, live_version),
                owner_headers(bidder2),
            ),
            expected_status=201,
        )
        assert accepted["amount_cents"] == 21000
        assert accepted["status"] == "ACTIVE"
        # The displaced-at-placement fallacy: the earlier 20000 bid stays ACTIVE.
        first_after = validate_success(api.get_bid(first["id"], REGISTRAR))
        assert first_after["status"] == "ACTIVE", (
            f"earlier lower bids remain ACTIVE until close, got {first_after['status']}"
        )


class TestBidRetraction:
    def test_retract_leading_rejected_nonleading_succeeds(self, api):
        """PRD §3.7: "retracting requires the bid to be `ACTIVE`, the acting owner
        to be the bid's `bidder_owner_id`, the auction still `OPEN`, and the bid
        not to be the highest-amount `ACTIVE` bid on its auction — the leader is
        locked in, and any violation fails with `ERR_BID_NOT_RETRACTABLE`. A
        successful retraction moves the bid to `RETRACTED`."

        Design: Corner/errors/retract_leading_rejected_nonleading_succeeds
        """
        scenario = setup_open_auction(serial="RTR100", appraised_value_cents=100000)
        bidder1 = register_owner("o1@x.com", "O One")
        bidder2 = register_owner("o2@x.com", "O Two")
        bid1 = place_bid(
            scenario["auction"]["id"], bidder1, 20000, scenario["auction_version"]
        )
        bid2 = place_bid(
            scenario["auction"]["id"], bidder2, 21000,
            get_auction_version(scenario["auction"]["id"]),
        )
        # The leading bid (21000) is locked in.
        resp = api.retract_bid(bid2["id"], owner_headers(bidder2))
        validate_error(resp, ApiErrorId.ERR_BID_NOT_RETRACTABLE, expected_status=409)
        # The non-leading bid (20000) may be retracted.
        retracted = validate_success(api.retract_bid(bid1["id"], owner_headers(bidder1)))
        assert retracted["status"] == "RETRACTED", (
            f"non-leading retraction must succeed, got {retracted['status']}"
        )


class TestBidAuctionStateGating:
    def test_bid_blocked_when_auction_not_open(self, api):
        """PRD §3.7: "Bids are accepted only while the auction is `OPEN`
        (otherwise `ERR_AUCTION_NOT_OPEN`) and the current time is no later than
        `ends_at` (otherwise `ERR_AUCTION_WINDOW_EXPIRED`)."

        The auction is SCHEDULED and the clock sits inside the bidding window; the
        state gate, not the time window, rejects the bid.

        Design: Difficulty/cross_entity_state_dependency/bid_blocked_when_auction_not_open
        """
        _org, intake = setup_unclaimed_intake(serial="XDP200", appraised_value_cents=100000)
        auction = create_auction_for_intake(intake)  # stays SCHEDULED
        bidder = register_owner("o1@x.com", "O One")
        set_clock("2026-06-05T00:00:00Z")  # inside [starts_at, ends_at]
        resp = api.place_bid(
            auction["id"],
            create_bid_payload(25000, auction["version"]),
            owner_headers(bidder),
        )
        validate_error(resp, ApiErrorId.ERR_AUCTION_NOT_OPEN, expected_status=409)

    def test_bid_blocked_when_auction_cancelled(self, api):
        """PRD §3.7: "Bids are accepted only while the auction is `OPEN`
        (otherwise `ERR_AUCTION_NOT_OPEN`) and the current time is no later than
        `ends_at` (otherwise `ERR_AUCTION_WINDOW_EXPIRED`)."
        PRD §3.7: "From `SCHEDULED` an auction may always be cancelled; from `OPEN`
        cancellation requires that zero bids exist (otherwise
        `ERR_AUCTION_HAS_BIDS`);"

        Design: Difficulty/cross_entity_state_dependency/bid_blocked_when_auction_not_open
        """
        _org, intake = setup_unclaimed_intake(serial="XDP201", appraised_value_cents=100000)
        auction = create_auction_for_intake(intake)  # SCHEDULED
        cancelled = validate_success(api.cancel_auction(auction["id"], REGISTRAR))
        bidder = register_owner("o1@x.com", "O One")
        set_clock("2026-06-05T00:00:00Z")  # inside the (now void) window
        # OCC (stage 8) precedes the state-machine check (stage 10), so the bid
        # must carry the auction's post-cancel version for the state error to
        # surface.
        resp = api.place_bid(
            auction["id"],
            create_bid_payload(25000, cancelled["version"]),
            owner_headers(bidder),
        )
        validate_error(resp, ApiErrorId.ERR_AUCTION_NOT_OPEN, expected_status=409)


class TestTemporalVsFiscalPriority:
    def test_auction_window_expired_beats_bid_below_minimum(self, api):
        """PRD §2.6: "Every request passes through a fixed validation pipeline, and
        the stages are evaluated in a strict order — a failure at an earlier stage
        surfaces its error and masks every later-stage check."
        PRD §2.6: "14. **Temporal windows** — ...; failures yield ..." precedes
        "15. **Fiscal and quota checks** — bid minimums and event seat capacity,
        evaluated last; failures yield `ERR_BID_BELOW_MINIMUM` or
        `ERR_EVENT_CAPACITY_FULL`."

        The bid is BOTH past the window and below the reserve; the temporal error
        surfaces.

        Design: Difficulty/priority_pair_validation_conflict/auction_window_expired_beats_bid_below_minimum
        """
        scenario = setup_open_auction(serial="ZZZ888", appraised_value_cents=100000)
        bidder = register_owner("o1@x.com", "O One")
        set_clock("2026-06-11T00:00:00Z")  # past ends_at 2026-06-10
        resp = api.place_bid(
            scenario["auction"]["id"],
            create_bid_payload(15000, scenario["auction_version"]),  # also below reserve
            owner_headers(bidder),
        )
        validate_error(resp, ApiErrorId.ERR_AUCTION_WINDOW_EXPIRED, expected_status=409)

    def test_auction_window_expired_with_valid_amount(self, api):
        """PRD §3.7: "Bids are accepted only while the auction is `OPEN`
        (otherwise `ERR_AUCTION_NOT_OPEN`) and the current time is no later than
        `ends_at` (otherwise `ERR_AUCTION_WINDOW_EXPIRED`)."

        Design: Difficulty/priority_pair_validation_conflict/auction_window_expired_beats_bid_below_minimum
        """
        scenario = setup_open_auction(serial="ZZZ889", appraised_value_cents=100000)
        bidder = register_owner("o1@x.com", "O One")
        set_clock("2026-06-11T00:00:00Z")  # past ends_at 2026-06-10
        resp = api.place_bid(
            scenario["auction"]["id"],
            create_bid_payload(25000, scenario["auction_version"]),  # amount is fine
            owner_headers(bidder),
        )
        validate_error(resp, ApiErrorId.ERR_AUCTION_WINDOW_EXPIRED, expected_status=409)


class TestBidOcc:
    def test_bid_place_stale_auction_version_rejected(self, api):
        """PRD §2.9: "Placing a bid must likewise carry `expected_auction_version`,
        set to the `version` of the target `Auction` the client last observed.
        Because every accepted bid itself advances the auction's `version` (§3.7),
        a bidder working from an outdated auction view is rejected with
        `ERR_STALE_VERSION` (HTTP 412) and must re-read the auction before bidding
        again."

        Design: Corner/cross_cutting_layers/bid_place_stale_auction_version_rejected
        """
        scenario = setup_open_auction(serial="OCC200", appraised_value_cents=100000)
        bidder1 = register_owner("o1@x.com", "O One")
        bidder2 = register_owner("o2@x.com", "O Two")
        stale_version = scenario["auction_version"]
        accepted = validate_success(
            api.place_bid(
                scenario["auction"]["id"],
                create_bid_payload(20000, stale_version),
                owner_headers(bidder1),
            ),
            expected_status=201,
        )
        assert accepted["status"] == "ACTIVE"
        # The accepted bid bumped the auction version; the stale view is rejected.
        resp = api.place_bid(
            scenario["auction"]["id"],
            create_bid_payload(21000, stale_version),
            owner_headers(bidder2),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
