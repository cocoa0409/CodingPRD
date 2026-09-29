"""Non-linear state movement: a bounded negotiation cycle and two parallel
status dimensions on one show row.

Every test builds its own world through the declared endpoints, because the
database is emptied before each one runs.
"""

from test_helpers import api_errors as E
from test_helpers import (
    assert_market_exposure,
    assert_timestamp_equals,
    get_success_data,
    validate_error,
    validate_success,
)

NEGOTIATION_CLOCK = "2026-08-01T00:00:00.000Z"
EXPECTED_FIRST_EXPIRY = "2026-08-04T00:00:00.000Z"
OPENING_GUARANTEE = 5_000_000
ROUND_ONE_COUNTER = 5_500_000
ROUND_TWO_GUARANTEE = 5_250_000
ROUND_TWO_COUNTER = 5_400_000
ROUND_THREE_GUARANTEE = 5_350_000
REFUSED_COUNTER = 5_450_000
NEGOTIATION_EXPOSURE_LIMIT = 20_000_000


def _draft_offer_on_a_planned_show(build):
    """A market, an act, a building, a PLANNED show and one DRAFT offer.

    The clock stays at the default instant for the whole instance so the 72-hour
    offer expiry never fires while the negotiation runs.
    """
    build.set_clock(NEGOTIATION_CLOCK)
    market = build.market(
        name="Mid Atlantic",
        region_code="MAT",
        guarantee_exposure_limit_cents=NEGOTIATION_EXPOSURE_LIMIT,
    )
    artist = build.artist(
        name="Copper Halo",
        agency="Beltway Bookings",
        tier="ARENA",
        historical_sellthrough_pct=76.00,
        withholding_pct=0,
    )
    venue = build.venue(
        market["id"],
        name="Tidewater Coliseum",
        gross_capacity=4_000,
        facility_fee_cents_per_ticket=200,
        ticket_tax_pct=6.00,
    )
    show = build.show(
        artist["id"],
        venue["id"],
        event_at="2026-11-14T02:00:00.000Z",
        load_in_at="2026-11-13T14:00:00.000Z",
        load_out_at="2026-11-14T08:00:00.000Z",
        announce_at="2026-09-01T15:00:00.000Z",
        venue_arrangement="CO_PROMOTE",
        copromote_venue_share_pct=12.00,
        venue_expense_pct_production=40.00,
        venue_expense_pct_marketing=0,
        venue_expense_pct_staffing=100.00,
        venue_expense_pct_hospitality=0,
    )
    offer = build.offer(
        show["id"],
        expected_show_version=show["version"],
        deal_structure="GUARANTEE_PLUS_BACKEND",
        guarantee_cents=OPENING_GUARANTEE,
        deposit_cents=1_000_000,
        expense_cap_cents=4_000_000,
        backend_split_artist_pct=85.00,
    )
    return {
        "market": market,
        "artist": artist,
        "venue": venue,
        "show": show,
        "offer": offer,
        "rep": build.artist_rep(artist["id"]),
    }


def _negotiate_to_the_round_limit(api, build, ctx):
    """Drive the offer around the cycle until `round_index` reaches 3."""
    offer_id = ctx["offer"]["id"]
    validate_success(api.submit_offer(offer_id, build.buyer))
    validate_success(
        api.counter_offer(
            offer_id,
            ctx["rep"],
            counter_guarantee_cents=ROUND_ONE_COUNTER,
            counter_backend_split_artist_pct=90.00,
            counter_note="round 1 counter - the agency asks for a higher floor",
        )
    )
    validate_success(
        api.submit_offer(
            offer_id,
            build.buyer,
            guarantee_cents=ROUND_TWO_GUARANTEE,
            backend_split_artist_pct=87.00,
        )
    )
    validate_success(
        api.counter_offer(
            offer_id,
            ctx["rep"],
            counter_guarantee_cents=ROUND_TWO_COUNTER,
            counter_backend_split_artist_pct=88.00,
            counter_note="round 2 counter - split the difference",
        )
    )
    return validate_success(
        api.submit_offer(
            offer_id,
            build.buyer,
            guarantee_cents=ROUND_THREE_GUARANTEE,
            backend_split_artist_pct=88.00,
        )
    )


class TestOfferNegotiationCycle:
    """SUBMITTED -> COUNTERED -> SUBMITTED, bounded by `round_index`."""

    def test_the_submit_and_counter_edges_leave_the_round_index_alone(self, api, build):
        """PRD section 3.2: "On success the new offer is created in status `DRAFT` with
        `round_index` 1" — and "The submission stamps `submitted_at` with the current
        logical clock and sets `expires_at` to exactly 72 hours — three days — after
        that instant." Countering then reverses direction: "Countering also clears
        `expires_at` to null".

        Design: Difficulty/non_linear_state_machine/offer_negotiation_cycles_submitted_countered_submitted_until_round_limit
        """
        ctx = _draft_offer_on_a_planned_show(build)
        assert ctx["offer"]["status"] == "DRAFT"
        assert ctx["offer"]["round_index"] == 1

        submitted = validate_success(api.submit_offer(ctx["offer"]["id"], build.buyer))

        assert submitted["status"] == "SUBMITTED"
        assert submitted["round_index"] == 1
        assert_timestamp_equals(submitted["submitted_at"], NEGOTIATION_CLOCK)
        assert_timestamp_equals(submitted["expires_at"], EXPECTED_FIRST_EXPIRY)

        countered = validate_success(
            api.counter_offer(
                ctx["offer"]["id"],
                ctx["rep"],
                counter_guarantee_cents=ROUND_ONE_COUNTER,
                counter_backend_split_artist_pct=90.00,
                counter_note="round 1 counter - the agency asks for a higher floor",
            )
        )

        assert countered["status"] == "COUNTERED"
        assert countered["round_index"] == 1
        assert countered["expires_at"] is None
        assert countered["counter_guarantee_cents"] == ROUND_ONE_COUNTER

    def test_re_submitting_a_countered_offer_is_the_only_edge_that_increments_the_round(
        self, api, build
    ):
        """PRD section 3.2: "The loop closes when the promoter answers a counter:
        re-submitting moves the offer `COUNTERED → SUBMITTED` again." On that edge,
        "`round_index` increments by 1, `submitted_at` is re-stamped from the logical
        clock and `expires_at` is set 72 hours later".

        Design: Difficulty/non_linear_state_machine/offer_negotiation_cycles_submitted_countered_submitted_until_round_limit
        """
        ctx = _draft_offer_on_a_planned_show(build)
        offer_id = ctx["offer"]["id"]
        validate_success(api.submit_offer(offer_id, build.buyer))
        validate_success(
            api.counter_offer(
                offer_id,
                ctx["rep"],
                counter_guarantee_cents=ROUND_ONE_COUNTER,
                counter_backend_split_artist_pct=90.00,
                counter_note="round 1 counter - the agency asks for a higher floor",
            )
        )

        second_round = validate_success(
            api.submit_offer(
                offer_id,
                build.buyer,
                guarantee_cents=ROUND_TWO_GUARANTEE,
                backend_split_artist_pct=87.00,
            )
        )

        # The offer has re-entered a state it already occupied.
        assert second_round["status"] == "SUBMITTED"
        assert second_round["round_index"] == 2
        assert second_round["guarantee_cents"] == ROUND_TWO_GUARANTEE
        assert second_round["backend_split_artist_pct"] == 87.00
        assert_timestamp_equals(second_round["expires_at"], EXPECTED_FIRST_EXPIRY)
        # The counter_* fields stay as the record of the round just answered.
        assert second_round["counter_guarantee_cents"] == ROUND_ONE_COUNTER

        validate_success(
            api.counter_offer(
                offer_id,
                ctx["rep"],
                counter_guarantee_cents=ROUND_TWO_COUNTER,
                counter_backend_split_artist_pct=88.00,
                counter_note="round 2 counter - split the difference",
            )
        )
        third_round = validate_success(
            api.submit_offer(
                offer_id,
                build.buyer,
                guarantee_cents=ROUND_THREE_GUARANTEE,
                backend_split_artist_pct=88.00,
            )
        )

        assert third_round["status"] == "SUBMITTED"
        assert third_round["round_index"] == 3
        assert third_round["guarantee_cents"] == ROUND_THREE_GUARANTEE

    def test_a_fourth_round_is_refused_and_leaves_the_cycle_exactly_where_it_was(
        self, api, build
    ):
        """PRD section 3.2: "Negotiation is capped at three rounds: neither a counter
        nor a re-submission may proceed once `round_index` has reached 3, and an attempt
        to go a fourth round is rejected with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` (HTTP
        409)." Per section 2.9, when a rule fires "No later rule is evaluated once one
        has fired, and no side effect of the operation runs."

        Design: Difficulty/non_linear_state_machine/offer_negotiation_cycles_submitted_countered_submitted_until_round_limit
        """
        ctx = _draft_offer_on_a_planned_show(build)
        offer_id = ctx["offer"]["id"]
        third_round = _negotiate_to_the_round_limit(api, build, ctx)
        assert third_round["round_index"] == 3

        refused = api.counter_offer(
            offer_id,
            ctx["rep"],
            counter_guarantee_cents=REFUSED_COUNTER,
            counter_backend_split_artist_pct=88.00,
            counter_note="round 3 counter - the loop is already exhausted",
        )

        validate_error(refused, E.ERR_NEGOTIATION_ROUNDS_EXHAUSTED, 409)

        after = build.read_offer(offer_id)
        assert after["status"] == "SUBMITTED"
        assert after["round_index"] == 3
        assert after["guarantee_cents"] == ROUND_THREE_GUARANTEE
        assert after["counter_guarantee_cents"] == ROUND_TWO_COUNTER
        assert after["version"] == third_round["version"]

    def test_the_bounded_cycle_still_exits_into_acceptance(self, api, build):
        """PRD section 3.3: "the offer moves `SUBMITTED → ACCEPTED` and, in the same
        request, the show moves `PLANNED → CONFIRMED`" — and "The show's
        `committed_guarantee_cents` is set to the accepted offer's `guarantee_cents`".

        Design: Difficulty/non_linear_state_machine/offer_negotiation_cycles_submitted_countered_submitted_until_round_limit
        """
        ctx = _draft_offer_on_a_planned_show(build)
        offer_id = ctx["offer"]["id"]
        _negotiate_to_the_round_limit(api, build, ctx)
        validate_error(
            api.counter_offer(
                offer_id,
                ctx["rep"],
                counter_guarantee_cents=REFUSED_COUNTER,
                counter_backend_split_artist_pct=88.00,
                counter_note="round 3 counter - the loop is already exhausted",
            ),
            E.ERR_NEGOTIATION_ROUNDS_EXHAUSTED,
            409,
        )

        accepted = validate_success(api.accept_offer(offer_id, ctx["rep"]))

        assert accepted["status"] == "ACCEPTED"
        assert accepted["guarantee_cents"] == ROUND_THREE_GUARANTEE

        show = build.read_show(ctx["show"]["id"])
        assert show["show_status"] == "CONFIRMED"
        assert show["committed_guarantee_cents"] == ROUND_THREE_GUARANTEE

        market = build.read_market(ctx["market"]["id"])
        assert_market_exposure(market, ROUND_THREE_GUARANTEE, 26.75, "OPEN")


SELLING_CLOCK = "2026-08-10T15:00:00.000Z"
PAUSE_REASON = "chargeback pattern on a bulk order under review"
TICKETS_SOLD_BEFORE_PAUSE = 100
PAUSE_TICKET_PRICE = 2_000
GROSS_BEFORE_PAUSE = TICKETS_SOLD_BEFORE_PAUSE * PAUSE_TICKET_PRICE


def _selling_show_with_one_tier(build):
    """A show that is ON_SALE and SELLING with 100 of 500 GA seats sold.

    The building charges no ticket tax and no facility fee, so the only
    deduction on the receipts ladder is the card charge.
    """
    build.set_clock(NEGOTIATION_CLOCK)
    market = build.market(
        name="Southeast", region_code="SEA", guarantee_exposure_limit_cents=10_000_000
    )
    artist = build.artist(
        name="Palmetto Riot",
        agency="Lowcountry Talent",
        tier="THEATER",
        historical_sellthrough_pct=64.00,
        withholding_pct=0,
    )
    venue = build.venue(
        market["id"],
        name="Magnolia Hall",
        gross_capacity=900,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
    )
    show = build.show(
        artist["id"],
        venue["id"],
        event_at="2026-09-20T02:00:00.000Z",
        load_in_at="2026-09-19T14:00:00.000Z",
        load_out_at="2026-09-20T08:00:00.000Z",
        announce_at=SELLING_CLOCK,
        venue_arrangement="RENTAL",
        rental_fee_cents=100_000,
    )
    build.accepted_offer(
        show["id"],
        artist["id"],
        expected_show_version=show["version"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=1_000_000,
        deposit_cents=0,
        expense_cap_cents=1_000_000,
    )
    ga = build.tier(
        show["id"], tier_name="GA", price_cents=PAUSE_TICKET_PRICE, allocation_qty=500
    )
    build.set_clock(SELLING_CLOCK)
    get_success_data(build.api.put_show_on_sale(show["id"], build.buyer))
    build.sell(ga["id"], TICKETS_SOLD_BEFORE_PAUSE)
    return {
        "market": market,
        "artist": artist,
        "venue": venue,
        "show": build.read_show(show["id"]),
        "ga": build.read_tier(ga["id"]),
    }


class TestShowStatusAndSalesStatusAreParallelDimensions:
    """One row, two independent status dimensions and one shared join trigger."""

    def test_pausing_sales_moves_the_ticketing_dimension_only(self, api, build):
        """PRD section 3.5: "Pausing — available to a `TalentBuyer` or a `RiskOfficer`,
        and requiring a `reason` — moves `sales_status` `SELLING → PAUSED` and cascades
        every tier in `ON_SALE` to `PAUSED`, while leaving `show_status` completely
        untouched at `ON_SALE`."

        Design: Difficulty/non_linear_state_machine/show_status_and_sales_status_move_as_independent_parallel_dimensions
        """
        ctx = _selling_show_with_one_tier(build)
        assert ctx["show"]["show_status"] == "ON_SALE"
        assert ctx["show"]["sales_status"] == "SELLING"

        paused = validate_success(
            api.pause_sales(ctx["show"]["id"], PAUSE_REASON, build.risk)
        )

        assert paused["sales_status"] == "PAUSED"
        assert paused["show_status"] == "ON_SALE"

        tier = build.read_tier(ctx["ga"]["id"])
        assert tier["status"] == "PAUSED"
        assert tier["sold_qty"] == TICKETS_SOLD_BEFORE_PAUSE

    def test_a_paused_tier_accepts_no_sales_and_the_refusal_has_no_side_effect(
        self, api, build
    ):
        """PRD section 3.5: "The tier must be `ON_SALE` — a `DRAFT`, `PAUSED` or
        `CLOSED` tier accepts no sales". Section 2.9 places that rejection at
        "`ERR_INVALID_STATE` when the target sits in a non-terminal state from which the
        requested trigger has no declared transition", and adds that "No later rule is
        evaluated once one has fired, and no side effect of the operation runs."

        Design: Difficulty/non_linear_state_machine/show_status_and_sales_status_move_as_independent_parallel_dimensions
        """
        ctx = _selling_show_with_one_tier(build)
        validate_success(api.pause_sales(ctx["show"]["id"], PAUSE_REASON, build.risk))
        before = build.read_tier(ctx["ga"]["id"])

        refused = api.record_sales(ctx["ga"]["id"], build.buyer, qty=10)

        validate_error(refused, E.ERR_INVALID_STATE, 409)

        after = build.read_tier(ctx["ga"]["id"])
        assert after["sold_qty"] == TICKETS_SOLD_BEFORE_PAUSE
        assert after["gross_sold_cents"] == GROSS_BEFORE_PAUSE
        assert after["available_qty"] == before["available_qty"]
        assert after["version"] == before["version"]

    def test_resuming_sales_returns_the_ticketing_dimension_without_moving_show_status(
        self, api, build
    ):
        """PRD section 3.1: "Pausing or resuming sales never touches `show_status`: a
        paused show is still `ON_SALE` and still settles normally." Section 3.5 adds
        that "Resuming, available to a `TalentBuyer`, moves `sales_status` `PAUSED →
        SELLING` provided `show_status` is `ON_SALE`, and cascades every `PAUSED` tier
        back to `ON_SALE`." and that "This is a true cycle: a show may travel `SELLING →
        PAUSED → SELLING` any number of times".

        Design: Difficulty/non_linear_state_machine/show_status_and_sales_status_move_as_independent_parallel_dimensions
        """
        ctx = _selling_show_with_one_tier(build)
        paused = validate_success(
            api.pause_sales(ctx["show"]["id"], PAUSE_REASON, build.risk)
        )
        assert paused["show_status"] == "ON_SALE"

        resumed = validate_success(api.resume_sales(ctx["show"]["id"], build.buyer))

        assert resumed["sales_status"] == "SELLING"
        assert resumed["show_status"] == "ON_SALE"

        tier = build.read_tier(ctx["ga"]["id"])
        assert tier["status"] == "ON_SALE"
        assert tier["sold_qty"] == TICKETS_SOLD_BEFORE_PAUSE
        assert tier["gross_sold_cents"] == GROSS_BEFORE_PAUSE

    def test_performing_is_the_single_join_trigger_that_advances_both_dimensions(
        self, api, build
    ):
        """PRD section 3.7: "The same call closes ticketing: `sales_status` moves to
        `CLOSED`, and every tier of the show sitting in `DRAFT`, `ON_SALE` or `PAUSED`
        moves to `CLOSED` with `available_qty` set to 0." The same paragraph adds that
        "The show's `adjusted_gross_cents` is recomputed and thereafter frozen, since no
        further sale can change it."

        Design: Difficulty/non_linear_state_machine/show_status_and_sales_status_move_as_independent_parallel_dimensions
        """
        ctx = _selling_show_with_one_tier(build)
        validate_success(api.pause_sales(ctx["show"]["id"], PAUSE_REASON, build.risk))
        validate_success(api.resume_sales(ctx["show"]["id"], build.buyer))
        build.set_clock("2026-09-20T06:00:00.000Z")

        performed = validate_success(api.perform_show(ctx["show"]["id"], build.buyer))

        assert performed["show_status"] == "PERFORMED"
        assert performed["sales_status"] == "CLOSED"
        # 200,000 gross, zero ticket tax, zero facility fee, 2.5 percent card charge.
        assert performed["adjusted_gross_cents"] == GROSS_BEFORE_PAUSE - 5_000 == 195_000

        tier = build.read_tier(ctx["ga"]["id"])
        assert tier["status"] == "CLOSED"
        assert tier["available_qty"] == 0
        assert tier["sold_qty"] == TICKETS_SOLD_BEFORE_PAUSE
