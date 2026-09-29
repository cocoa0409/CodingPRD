"""Lifecycle walks across the state machines the contract declares.

Every test here walks one declared edge, or one declared side effect of an
edge, and quotes the sentence of the contract that states the rule.
"""

from test_helpers import api_errors as E
from test_helpers import (
    assert_market_exposure,
    assert_timestamp_equals,
    factories,
    get_success_data,
    make_tour_accountant_headers,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

ZERO_FEE_WORLD = {
    "guarantee_exposure_limit_cents": 5_000_000,
    "gross_capacity": 1_000,
    "facility_fee_cents_per_ticket": 0,
    "ticket_tax_pct": 0,
}


def zero_fee(**overrides):
    """A market, act and venue whose ticket tax and facility fee are both 0."""
    kwargs = dict(ZERO_FEE_WORLD)
    kwargs.update(overrides)
    return kwargs


def rental_terms(rental_fee_cents=150_000, **overrides):
    """RENTAL show terms with every co-promote percentage explicitly 0."""
    terms = {
        "venue_arrangement": "RENTAL",
        "rental_fee_cents": rental_fee_cents,
        "copromote_venue_share_pct": 0,
        "venue_expense_pct_production": 0,
        "venue_expense_pct_marketing": 0,
        "venue_expense_pct_staffing": 0,
        "venue_expense_pct_hospitality": 0,
    }
    terms.update(overrides)
    return terms


class TestDeclaredInitialStates:
    """Every machine's birth state, read straight off the create response."""

    def test_a_newly_booked_show_starts_planned_and_pre_sale(self, api, build):
        """PRD 3.1: "A newly booked show starts in `show_status` `PLANNED` and `sales_status` `PRE_SALE`, commits no guarantee, and contributes nothing to its market's exposure."

        Design: Corner/state_machines/every_machine_starts_in_its_declared_initial_state
        """
        ctx = build.world(**zero_fee())
        show = validate_success(
            api.create_show(
                factories.show_payload(
                    ctx["artist"]["id"], ctx["venue"]["id"], **rental_terms()
                ),
                build.buyer,
            ),
            201,
        )
        assert show["show_status"] == "PLANNED"
        assert show["sales_status"] == "PRE_SALE"
        assert show["committed_guarantee_cents"] == 0
        assert_market_exposure(build.read_market(ctx["market"]["id"]), 0, 0, "OPEN")

    def test_a_new_offer_is_created_in_draft_at_round_one(self, api, build):
        """PRD 3.2: "On success the new offer is created in status `DRAFT` with `round_index` 1, and every **other** offer on the same show whose status is `SUBMITTED` or `COUNTERED` is moved to `SUPERSEDED`."

        Design: Corner/state_machines/every_machine_starts_in_its_declared_initial_state
        """
        ctx = build.planned_show(show=rental_terms(), **zero_fee())
        offer = validate_success(
            api.create_offer(
                factories.offer_payload(
                    ctx["show"]["id"],
                    ctx["show"]["version"],
                    guarantee_cents=500_000,
                    deposit_cents=100_000,
                    expense_cap_cents=1_000_000,
                ),
                build.buyer,
            ),
            201,
        )
        assert offer["status"] == "DRAFT"
        assert offer["round_index"] == 1

    def test_a_new_budget_line_is_created_active_and_within_tolerance(self, api, build):
        """PRD 3.6: "A new line is created with `actual_cents` 0, `variance_cents` 0, `variance_pct` 0, `variance_status` `WITHIN_TOLERANCE`, `required_approver_role` `NONE`, `approved_cap_cents` null, `variance_decided_by_user_id` null, `variance_justification` null, `settlement_expense_cents` 0, and lifecycle `status` `ACTIVE`."

        Design: Corner/state_machines/every_machine_starts_in_its_declared_initial_state
        """
        ctx = build.confirmed_show(
            guarantee_cents=500_000,
            deposit_cents=0,
            expense_cap_cents=1_000_000,
            show=rental_terms(),
            **zero_fee(),
        )
        line = validate_success(
            api.create_budget_line(
                factories.budget_line_payload(
                    ctx["show"]["id"],
                    category="PRODUCTION",
                    description="backline rental",
                    budgeted_cents=100_000,
                    is_artist_deductible=False,
                ),
                build.accountant,
            ),
            201,
        )
        assert line["actual_cents"] == 0
        assert line["variance_cents"] == 0
        assert float(line["variance_pct"]) == 0
        assert line["variance_status"] == "WITHIN_TOLERANCE"
        assert line["required_approver_role"] == "NONE"
        assert line["approved_cap_cents"] is None
        assert line["variance_decided_by_user_id"] is None
        assert line["variance_justification"] is None
        assert line["settlement_expense_cents"] == 0
        assert line["status"] == "ACTIVE"

    def test_a_new_vendor_invoice_is_created_submitted_and_unpapered(self, api, build):
        """PRD 3.6: "The invoice is created in status `SUBMITTED` with `resubmit_count` 0, `verified_by_user_id` and `approved_by_user_id` null, and `dispute_reason` null"

        Design: Corner/state_machines/every_machine_starts_in_its_declared_initial_state
        """
        ctx = build.confirmed_show(
            guarantee_cents=500_000,
            deposit_cents=0,
            expense_cap_cents=1_000_000,
            show=rental_terms(),
            **zero_fee(),
        )
        line = build.budget_line(
            ctx["show"]["id"], category="PRODUCTION", budgeted_cents=100_000
        )
        invoice = validate_success(
            api.create_vendor_invoice(
                factories.vendor_invoice_payload(
                    ctx["show"]["id"], line["id"], amount_cents=100_000
                ),
                build.accountant,
            ),
            201,
        )
        assert invoice["status"] == "SUBMITTED"
        assert invoice["resubmit_count"] == 0
        assert invoice["verified_by_user_id"] is None
        assert invoice["approved_by_user_id"] is None
        assert invoice["dispute_reason"] is None

    def test_a_new_ticket_tier_is_born_draft_with_its_whole_allocation_available(
        self, api, build
    ):
        """PRD 3.4: "A new tier is born in status `DRAFT` with `sold_qty` 0, `gross_sold_cents` 0, `comp_qty` 0, `held_qty` 0, `available_qty` equal to its `allocation_qty`, `price_revision_count` 0 and `last_price_cents` null."

        Design: Corner/state_machines/every_machine_starts_in_its_declared_initial_state
        """
        ctx = build.planned_show(show=rental_terms(), **zero_fee())
        tier = validate_success(
            api.create_ticket_tier(
                factories.ticket_tier_payload(
                    ctx["show"]["id"],
                    tier_name="GA",
                    price_cents=5_000,
                    allocation_qty=400,
                ),
                build.buyer,
            ),
            201,
        )
        assert tier["status"] == "DRAFT"
        assert tier["sold_qty"] == 0
        assert tier["gross_sold_cents"] == 0
        assert tier["comp_qty"] == 0
        assert tier["held_qty"] == 0
        assert tier["available_qty"] == tier["allocation_qty"] == 400
        assert tier["price_revision_count"] == 0
        assert tier["last_price_cents"] is None

    def test_a_new_ticket_hold_is_created_held(self, api, build):
        """PRD 3.5: "A hold is created in status `HELD` with `released_by_user_id` null."

        Design: Corner/state_machines/every_machine_starts_in_its_declared_initial_state
        """
        ctx = build.planned_show(show=rental_terms(), **zero_fee())
        tier = build.tier(
            ctx["show"]["id"], tier_name="GA", price_cents=5_000, allocation_qty=400
        )
        hold = validate_success(
            api.create_ticket_hold(
                factories.ticket_hold_payload(
                    tier["id"], kind="PROMOTER_HOLD", qty=10, holder="front of house"
                ),
                build.buyer,
            ),
            201,
        )
        assert hold["status"] == "HELD"
        assert hold["released_by_user_id"] is None

    def test_a_new_settlement_is_created_draft_with_every_money_field_zero(
        self, api, build
    ):
        """PRD 3.7: "The new **settlement** is created in status `DRAFT` with `reopen_count` 0, `deal_structure_applied` null, every money field 0, and `calculated_by_user_id`, `signed_by_user_id`, `paid_at`, `payment_method`, `payment_reference`, `dispute_reason` and `reopen_reason` all null."

        Design: Corner/state_machines/every_machine_starts_in_its_declared_initial_state
        """
        ctx = build.performed_show(show=rental_terms(), **zero_fee())
        settlement = validate_success(
            api.create_settlement(
                factories.settlement_payload(ctx["show"]["id"]), build.accountant
            ),
            201,
        )
        assert settlement["status"] == "DRAFT"
        assert settlement["reopen_count"] == 0
        assert settlement["deal_structure_applied"] is None
        money_fields = [key for key in settlement if key.endswith("_cents")]
        assert money_fields, "a settlement row carries money fields"
        for field in money_fields:
            assert settlement[field] == 0, f"{field} should be 0 on a DRAFT settlement"
        for field in (
            "calculated_by_user_id",
            "signed_by_user_id",
            "paid_at",
            "payment_method",
            "payment_reference",
            "dispute_reason",
            "reopen_reason",
        ):
            assert settlement[field] is None, f"{field} should be null on a DRAFT settlement"

    def test_a_new_cancellation_event_is_created_opened_and_stamped_from_the_clock(
        self, api, build
    ):
        """PRD 3.9: "The event is created in status `OPENED` with `occurred_at` stamped from the current logical clock, and that stamp starts the insurance filing window."

        Design: Corner/state_machines/every_machine_starts_in_its_declared_initial_state
        """
        ctx = build.planned_show(show=rental_terms(), **zero_fee())
        build.set_clock("2026-08-03T09:30:00.000Z")
        event = validate_success(
            api.create_cancellation_event(
                factories.cancellation_event_payload(
                    ctx["show"]["id"],
                    kind="CANCELLED",
                    reason="the act pulled the routing on medical advice",
                ),
                build.buyer,
            ),
            201,
        )
        assert event["status"] == "OPENED"
        assert_timestamp_equals(event["occurred_at"], "2026-08-03T09:30:00.000Z")


def performed_walk_show(build):
    """A performed zero-fee RENTAL show with 200 sold seats and one approved invoice."""
    build.set_clock("2026-08-01T00:00:00.000Z")
    market = build.market(
        name="Cascade Corridor", guarantee_exposure_limit_cents=5_000_000
    )
    artist = build.artist(name="The Long Walk", tier="THEATER", withholding_pct=0)
    venue = build.venue(
        market["id"],
        name="Walk Hall",
        gross_capacity=1_000,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
    )
    show = build.show(
        artist["id"],
        venue["id"],
        event_at="2026-09-01T02:00:00.000Z",
        load_in_at="2026-08-31T14:00:00.000Z",
        load_out_at="2026-09-01T08:00:00.000Z",
        announce_at="2026-08-05T15:00:00.000Z",
        **rental_terms(150_000),
    )
    offer = build.offer(
        show["id"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=500_000,
        deposit_cents=100_000,
        expense_cap_cents=1_000_000,
    )
    tier = build.tier(
        show["id"], tier_name="GA", price_cents=5_000, allocation_qty=500
    )
    get_success_data(build.api.submit_offer(offer["id"], build.buyer))
    get_success_data(
        build.api.accept_offer(offer["id"], build.artist_rep(artist["id"]))
    )
    line = build.budget_line(
        show["id"],
        category="PRODUCTION",
        description="backline rental",
        budgeted_cents=100_000,
        is_artist_deductible=False,
    )
    build.approved_invoice(show["id"], line["id"], 100_000, vendor_name="Backline Co")
    build.set_clock("2026-08-06T00:00:00.000Z")
    get_success_data(build.api.put_show_on_sale(show["id"], build.buyer))
    build.sell(tier["id"], 200)
    build.set_clock("2026-09-01T03:00:00.000Z")
    get_success_data(build.api.perform_show(show["id"], build.accountant))
    return {
        "market": market,
        "artist": artist,
        "venue": venue,
        "show": show,
        "offer": offer,
        "tier": tier,
        "line": line,
    }


class TestSettlementWalksEndToEnd:
    """DRAFT to CALCULATED to ARTIST_SIGNED to PAID on one performed show."""

    def test_the_settlement_walks_draft_calculated_artist_signed_and_paid(
        self, api, build
    ):
        """PRD 3.8: "`SIGN` moves the settlement `CALCULATED → ARTIST_SIGNED` and records `signed_by_user_id` as the responding rep's `X-User-ID`, unlocking payment."

        Design: Corner/state_machines/settlement_walks_draft_calculated_signed_paid_end_to_end
        """
        ctx = performed_walk_show(build)
        settlement = build.settlement(ctx["show"]["id"])
        assert settlement["status"] == "DRAFT"

        calculated = validate_success(
            api.calculate_settlement(settlement["id"], build.accountant)
        )
        assert calculated["status"] == "CALCULATED"
        assert calculated["deal_structure_applied"] == "FLAT_GUARANTEE"
        assert calculated["calculated_by_user_id"] == build.accountant["X-User-ID"]

        signed = validate_success(
            api.respond_to_settlement(
                settlement["id"],
                build.artist_rep(ctx["artist"]["id"]),
                response="SIGN",
            )
        )
        assert signed["status"] == "ARTIST_SIGNED"
        assert signed["signed_by_user_id"] == ctx["artist"]["id"]

        paid = validate_success(
            api.pay_settlement(
                settlement["id"],
                build.accountant_two,
                payment_method="WIRE",
                payment_reference="WIRE-77120",
            )
        )
        assert paid["status"] == "PAID"
        assert paid["payment_method"] == "WIRE"
        assert paid["payment_reference"] == "WIRE-77120"
        assert_timestamp_equals(paid["paid_at"], "2026-09-01T03:00:00.000Z")

    def test_the_calculation_freezes_the_adjusted_gross_waterfall(self, api, build):
        """PRD 3.7: "`gross_receipts_cents` is the show's accumulated `gross_sold_cents` at calculate time, valued at time-of-sale prices, plus its `transferred_in_gross_cents`."

        Design: Corner/state_machines/settlement_walks_draft_calculated_signed_paid_end_to_end
        """
        ctx = performed_walk_show(build)
        settlement = build.settlement(ctx["show"]["id"])
        calculated = validate_success(
            api.calculate_settlement(settlement["id"], build.accountant)
        )
        assert calculated["gross_receipts_cents"] == 1_000_000
        assert calculated["ticket_tax_cents"] == 0
        assert calculated["facility_fee_cents"] == 0
        assert calculated["credit_card_fee_cents"] == 25_000
        assert calculated["adjusted_gross_cents"] == 975_000

    def test_the_calculation_freezes_expense_recognition_and_artist_earnings(
        self, api, build
    ):
        """PRD 3.7: "`breakeven_cents` is then `allowed_expense_cents` plus the offer's `guarantee_cents` — the guarantee is part of breakeven, including for backend deals."

        Design: Corner/state_machines/settlement_walks_draft_calculated_signed_paid_end_to_end
        """
        ctx = performed_walk_show(build)
        settlement = build.settlement(ctx["show"]["id"])
        calculated = validate_success(
            api.calculate_settlement(settlement["id"], build.accountant)
        )
        assert calculated["total_settlement_expense_cents"] == 100_000
        assert calculated["allowed_expense_cents"] == 0
        assert calculated["breakeven_cents"] == 500_000
        assert calculated["artist_base_earnings_cents"] == 500_000
        assert calculated["artist_coop_contribution_cents"] == 0
        assert calculated["artist_earnings_cents"] == 500_000
        assert calculated["withholding_cents"] == 0
        assert calculated["deposit_credit_cents"] == 100_000
        assert calculated["payment_due_cents"] == 400_000

    def test_the_calculation_splits_the_rental_deal_and_closes_the_invariant(
        self, api, build
    ):
        """PRD 3.7: "Under `RENTAL`, `venue_expense_reimbursement_cents` is 0 — the promoter bears every expense — so `promoter_borne_expense_cents` equals `total_settlement_expense_cents`, and `venue_share_cents` is the show's flat `rental_fee_cents`, paid regardless of outcome."

        Design: Corner/state_machines/settlement_walks_draft_calculated_signed_paid_end_to_end
        """
        ctx = performed_walk_show(build)
        settlement = build.settlement(ctx["show"]["id"])
        calculated = validate_success(
            api.calculate_settlement(settlement["id"], build.accountant)
        )
        assert calculated["venue_expense_reimbursement_cents"] == 0
        assert calculated["promoter_borne_expense_cents"] == 100_000
        assert calculated["venue_share_cents"] == 150_000
        assert calculated["promoter_net_cents"] == 225_000
        assert calculated["adjusted_gross_cents"] == (
            calculated["artist_earnings_cents"]
            + calculated["promoter_borne_expense_cents"]
            + calculated["venue_share_cents"]
            + calculated["promoter_net_cents"]
        )

    def test_payment_closes_the_show_its_lines_and_re_prices_the_market(
        self, api, build
    ):
        """PRD 3.8: "**Hop one:** the show's `show_status` moves `PERFORMED → SETTLED`. **Hop two:** every budget line on the show whose lifecycle `status` is `ACTIVE` moves to `SETTLED`."

        Design: Corner/state_machines/settlement_walks_draft_calculated_signed_paid_end_to_end
        """
        ctx = performed_walk_show(build)
        assert_market_exposure(
            build.read_market(ctx["market"]["id"]), 500_000, 10.00, "OPEN"
        )
        settlement = build.settlement(ctx["show"]["id"])
        validate_success(api.calculate_settlement(settlement["id"], build.accountant))
        validate_success(
            api.respond_to_settlement(
                settlement["id"],
                build.artist_rep(ctx["artist"]["id"]),
                response="SIGN",
            )
        )
        validate_success(
            api.pay_settlement(
                settlement["id"],
                build.accountant_two,
                payment_method="WIRE",
                payment_reference="WIRE-77121",
            )
        )

        show = build.read_show(ctx["show"]["id"])
        assert show["show_status"] == "SETTLED"
        assert build.read_budget_line(ctx["line"]["id"])["status"] == "SETTLED"
        assert build.read_artist(ctx["artist"]["id"])["confirmed_show_count"] == 0
        market = build.read_market(ctx["market"]["id"])
        assert_market_exposure(market, 0, 0, "OPEN")
        assert market["settled_show_count"] == 1

    def test_payment_recomputes_the_market_performance_index_on_settled_shows(
        self, api, build
    ):
        """PRD 3.3: "the numerator is the sum of `promoter_net_cents` over the settlements of the market's shows whose `show_status` is `SETTLED`, and the denominator is the sum of `projected_promoter_net_cents` over those same settled shows."

        Design: Corner/state_machines/settlement_walks_draft_calculated_signed_paid_end_to_end
        """
        ctx = performed_walk_show(build)
        settlement = build.settlement(ctx["show"]["id"])
        validate_success(api.calculate_settlement(settlement["id"], build.accountant))
        validate_success(
            api.respond_to_settlement(
                settlement["id"],
                build.artist_rep(ctx["artist"]["id"]),
                response="SIGN",
            )
        )
        validate_success(
            api.pay_settlement(
                settlement["id"],
                build.accountant_two,
                payment_method="WIRE",
                payment_reference="WIRE-77122",
            )
        )
        show = build.read_show(ctx["show"]["id"])
        assert show["projected_adjusted_gross_cents"] == 2_437_500
        assert show["projected_promoter_net_cents"] == 1_837_500
        market = build.read_market(ctx["market"]["id"])
        assert market["performance_index"] == 12


class TestOnSaleAndPerformPreconditions:
    """Each declared gate on the two ticketing advances reports its own error."""

    def test_going_on_sale_before_the_announce_instant_is_refused_then_passes_on_it(
        self, api, build
    ):
        """PRD 3.4: "First, the current logical clock must have reached the show's `announce_at`; an earlier attempt yields `ERR_ANNOUNCE_DATE_NOT_REACHED` (HTTP 422)."

        Design: Corner/state_machines/on_sale_and_perform_preconditions_each_fail_with_their_own_error
        """
        ctx = build.confirmed_show(
            guarantee_cents=500_000,
            expense_cap_cents=1_000_000,
            show=rental_terms(announce_at="2026-09-15T00:00:00.000Z"),
            **zero_fee(),
        )
        build.tier(
            ctx["show"]["id"], tier_name="GA", price_cents=5_000, allocation_qty=400
        )
        validate_error(
            api.put_show_on_sale(ctx["show"]["id"], build.buyer),
            E.ERR_ANNOUNCE_DATE_NOT_REACHED,
        )
        assert build.read_show(ctx["show"]["id"])["show_status"] == "CONFIRMED"

        build.set_clock("2026-09-15T00:00:00.000Z")
        on_sale = validate_success(
            api.put_show_on_sale(ctx["show"]["id"], build.buyer)
        )
        assert on_sale["show_status"] == "ON_SALE"
        assert on_sale["sales_status"] == "SELLING"

    def test_going_on_sale_without_a_ticket_tier_is_refused(self, api, build):
        """PRD 3.4: "Second, the show must have at least one ticket tier; an empty tier set yields `ERR_NO_TICKET_TIERS` (HTTP 422)."

        Design: Corner/state_machines/on_sale_and_perform_preconditions_each_fail_with_their_own_error
        """
        ctx = build.confirmed_show(
            guarantee_cents=500_000,
            expense_cap_cents=1_000_000,
            show=rental_terms(announce_at="2026-08-01T00:00:00.000Z"),
            **zero_fee(),
        )
        validate_error(
            api.put_show_on_sale(ctx["show"]["id"], build.buyer), E.ERR_NO_TICKET_TIERS
        )
        show = build.read_show(ctx["show"]["id"])
        assert show["show_status"] == "CONFIRMED"
        assert show["sales_status"] == "PRE_SALE"

    def test_going_on_sale_from_planned_is_refused_as_an_undeclared_edge(
        self, api, build
    ):
        """PRD 2.9: "State legality — `ERR_INVALID_STATE` when the target sits in a non-terminal state from which the requested trigger has no declared transition, including sub-resource guards such as a show's ticketing state or a budget line's own lifecycle state."

        Design: Corner/state_machines/on_sale_and_perform_preconditions_each_fail_with_their_own_error
        """
        ctx = build.planned_show(
            show=rental_terms(announce_at="2026-08-01T00:00:00.000Z"), **zero_fee()
        )
        validate_error(
            api.put_show_on_sale(ctx["show"]["id"], build.buyer), E.ERR_INVALID_STATE
        )
        show = build.read_show(ctx["show"]["id"])
        assert show["show_status"] == "PLANNED"
        assert show["sales_status"] == "PRE_SALE"

    def test_a_tier_pushing_total_allocation_past_capacity_is_refused(
        self, api, build
    ):
        """PRD 3.4: "the sum of `allocation_qty` across the show's tiers, counting the tier being created, may not exceed the venue's `gross_capacity`, or the create is rejected with `ERR_VENUE_CAPACITY_EXCEEDED` (HTTP 422)"

        Design: Corner/state_machines/on_sale_and_perform_preconditions_each_fail_with_their_own_error
        """
        ctx = build.planned_show(
            show=rental_terms(announce_at="2026-08-01T00:00:00.000Z"),
            **zero_fee(gross_capacity=800),
        )
        build.tier(
            ctx["show"]["id"], tier_name="GA", price_cents=5_000, allocation_qty=600
        )
        validate_error(
            api.create_ticket_tier(
                factories.ticket_tier_payload(
                    ctx["show"]["id"],
                    tier_name="BALCONY",
                    price_cents=3_000,
                    allocation_qty=300,
                ),
                build.buyer,
            ),
            E.ERR_VENUE_CAPACITY_EXCEEDED,
        )
        tiers, _meta = validate_paginated(
            api.list_ticket_tiers(build.buyer, show_id=ctx["show"]["id"])
        )
        assert [tier["tier_name"] for tier in tiers] == ["GA"]

    def test_performing_before_the_event_instant_is_refused(self, api, build):
        """PRD 3.7: "the current logical clock must have reached the show's `event_at` — an earlier attempt yields `ERR_SHOW_NOT_YET_OCCURRED` (HTTP 422)"

        Design: Corner/state_machines/on_sale_and_perform_preconditions_each_fail_with_their_own_error
        """
        ctx = build.on_sale_show(
            guarantee_cents=500_000,
            expense_cap_cents=1_000_000,
            tiers=[{"tier_name": "GA", "price_cents": 5_000, "allocation_qty": 400}],
            announce_at="2026-08-01T00:00:00.000Z",
            show=rental_terms(event_at="2026-10-10T02:00:00.000Z"),
            **zero_fee(),
        )
        validate_error(
            api.perform_show(ctx["show"]["id"], build.accountant),
            E.ERR_SHOW_NOT_YET_OCCURRED,
        )
        show = build.read_show(ctx["show"]["id"])
        assert show["show_status"] == "ON_SALE"
        assert show["sales_status"] == "SELLING"

    def test_performing_at_the_event_instant_is_accepted(self, api, build):
        """PRD 3.7: "A `TalentBuyer` or a `TourAccountant` records it, moving `show_status` `ON_SALE → PERFORMED`, and the current logical clock must have reached the show's `event_at`"

        Design: Corner/state_machines/on_sale_and_perform_preconditions_each_fail_with_their_own_error
        """
        ctx = build.on_sale_show(
            guarantee_cents=500_000,
            expense_cap_cents=1_000_000,
            tiers=[{"tier_name": "GA", "price_cents": 5_000, "allocation_qty": 400}],
            announce_at="2026-08-01T00:00:00.000Z",
            show=rental_terms(event_at="2026-10-10T02:00:00.000Z"),
            **zero_fee(),
        )
        build.set_clock("2026-10-10T02:00:00.000Z")
        performed = validate_success(
            api.perform_show(ctx["show"]["id"], build.accountant)
        )
        assert performed["show_status"] == "PERFORMED"
        assert performed["sales_status"] == "CLOSED"


def paused_show_with_a_late_draft_tier(build):
    """An ON_SALE, sales-paused show carrying a tier created after the on-sale."""
    ctx = build.on_sale_show(
        guarantee_cents=600_000,
        expense_cap_cents=500_000,
        tiers=[{"tier_name": "GA", "price_cents": 5_000, "allocation_qty": 400}],
        announce_at="2026-08-01T00:00:00.000Z",
        show=rental_terms(
            90_000,
            event_at="2026-10-20T02:00:00.000Z",
            load_in_at="2026-10-19T14:00:00.000Z",
            load_out_at="2026-10-20T08:00:00.000Z",
        ),
        **zero_fee(),
    )
    build.sell(ctx["tiers"][0]["id"], 100)
    ctx["balcony"] = build.tier(
        ctx["show"]["id"], tier_name="BALCONY", price_cents=3_000, allocation_qty=200
    )
    get_success_data(
        build.api.pause_sales(
            ctx["show"]["id"], "weather advisory on the load-in day", build.risk
        )
    )
    ctx["show"] = build.read_show(ctx["show"]["id"])
    return ctx


class TestPerformSideEffects:
    """Recording the performance closes ticketing all the way down."""

    def test_performing_closes_every_tier_including_the_one_still_in_draft(
        self, api, build
    ):
        """PRD 3.7: "The same call closes ticketing: `sales_status` moves to `CLOSED`, and every tier of the show sitting in `DRAFT`, `ON_SALE` or `PAUSED` moves to `CLOSED` with `available_qty` set to 0."

        Design: Corner/state_machines/perform_applies_every_declared_side_effect_including_closing_a_draft_tier
        """
        ctx = paused_show_with_a_late_draft_tier(build)
        assert ctx["show"]["sales_status"] == "PAUSED"
        assert build.read_tier(ctx["tiers"][0]["id"])["status"] == "PAUSED"
        assert build.read_tier(ctx["balcony"]["id"])["status"] == "DRAFT"

        build.set_clock("2026-10-20T05:00:00.000Z")
        performed = validate_success(
            api.perform_show(ctx["show"]["id"], build.accountant)
        )
        assert performed["show_status"] == "PERFORMED"
        assert performed["sales_status"] == "CLOSED"

        general = build.read_tier(ctx["tiers"][0]["id"])
        balcony = build.read_tier(ctx["balcony"]["id"])
        assert general["status"] == "CLOSED"
        assert general["available_qty"] == 0
        assert balcony["status"] == "CLOSED"
        assert balcony["available_qty"] == 0

    def test_performing_leaves_the_sold_history_of_every_closed_tier_alone(
        self, api, build
    ):
        """PRD 3.7: "A tier created **after** the show went on sale never saw the on-sale cascade and is therefore still `DRAFT` at this point — it is closed here all the same, because `DRAFT` is not a state that survives a show going terminal."

        Design: Corner/state_machines/perform_applies_every_declared_side_effect_including_closing_a_draft_tier
        """
        ctx = paused_show_with_a_late_draft_tier(build)
        build.set_clock("2026-10-20T05:00:00.000Z")
        validate_success(api.perform_show(ctx["show"]["id"], build.accountant))

        general = build.read_tier(ctx["tiers"][0]["id"])
        balcony = build.read_tier(ctx["balcony"]["id"])
        assert general["sold_qty"] == 100
        assert general["gross_sold_cents"] == 500_000
        assert balcony["sold_qty"] == 0
        assert balcony["gross_sold_cents"] == 0
        show = build.read_show(ctx["show"]["id"])
        assert show["paid_tickets_sold"] == 100
        assert show["gross_sold_cents"] == 500_000

    def test_the_adjusted_gross_is_frozen_and_no_closed_tier_accepts_a_sale(
        self, api, build
    ):
        """PRD 3.7: "The show's `adjusted_gross_cents` is recomputed and thereafter frozen, since no further sale can change it."

        Design: Corner/state_machines/perform_applies_every_declared_side_effect_including_closing_a_draft_tier
        """
        ctx = paused_show_with_a_late_draft_tier(build)
        assert ctx["show"]["adjusted_gross_cents"] == 487_500

        build.set_clock("2026-10-20T05:00:00.000Z")
        performed = validate_success(
            api.perform_show(ctx["show"]["id"], build.accountant)
        )
        assert performed["adjusted_gross_cents"] == 487_500

        validate_error_is_one_of(
            api.record_sales(ctx["tiers"][0]["id"], build.buyer, qty=1),
            [E.ERR_INVALID_STATE, E.ERR_ALREADY_TERMINAL],
        )
        validate_error_is_one_of(
            api.record_sales(ctx["balcony"]["id"], build.buyer, qty=1),
            [E.ERR_INVALID_STATE, E.ERR_ALREADY_TERMINAL],
        )
        show = build.read_show(ctx["show"]["id"])
        assert show["adjusted_gross_cents"] == 487_500
        assert show["gross_sold_cents"] == 500_000
        assert show["paid_tickets_sold"] == 100


RESUBMIT_AMOUNTS = {1: 101_000, 2: 103_000, 3: 105_000}


def confirmed_show_with_a_submitted_invoice(build):
    """A CONFIRMED show, one 100,000-cent line and one SUBMITTED invoice on it."""
    ctx = build.confirmed_show(
        guarantee_cents=500_000,
        expense_cap_cents=1_000_000,
        show=rental_terms(),
        **zero_fee(),
    )
    ctx["line"] = build.budget_line(
        ctx["show"]["id"],
        category="PRODUCTION",
        description="staging package",
        budgeted_cents=100_000,
        is_artist_deductible=False,
    )
    ctx["invoice"] = build.submitted_invoice(
        ctx["show"]["id"],
        ctx["line"]["id"],
        100_000,
        vendor_name="Cascade Staging",
        documentation_ref="INV-LAP-0",
    )
    return ctx


def cycle_invoice(api, build, invoice_id, lap):
    """One SUBMITTED to VERIFIED to DISPUTED to SUBMITTED lap, verified by a fresh actor."""
    verified = validate_success(
        api.verify_vendor_invoice(
            invoice_id, make_tour_accountant_headers(f"u-acct-verifier-{lap}")
        )
    )
    disputed = validate_success(
        api.dispute_vendor_invoice(
            invoice_id,
            build.accountant,
            dispute_reason=f"lap {lap} packet page does not match the vendor total",
        )
    )
    resubmitted = validate_success(
        api.resolve_vendor_invoice_dispute(
            invoice_id,
            build.accountant,
            outcome="RESUBMIT",
            amount_cents=RESUBMIT_AMOUNTS[lap],
            documentation_ref=f"INV-LAP-{lap}",
        )
    )
    return verified, disputed, resubmitted


class TestVendorInvoiceDisputeCycle:
    """The invoice cycle is a true loop with no round cap of its own."""

    def test_the_invoice_cycles_verified_disputed_submitted_three_times(
        self, api, build
    ):
        """PRD 3.6: "A row may travel `SUBMITTED → VERIFIED → DISPUTED → SUBMITTED` any number of times."

        Design: Corner/state_machines/vendor_invoice_cycles_submitted_verified_disputed_submitted_three_times
        """
        ctx = confirmed_show_with_a_submitted_invoice(build)
        assert ctx["invoice"]["status"] == "SUBMITTED"
        for lap in (1, 2, 3):
            verified, disputed, resubmitted = cycle_invoice(
                api, build, ctx["invoice"]["id"], lap
            )
            assert verified["status"] == "VERIFIED"
            assert disputed["status"] == "DISPUTED"
            assert resubmitted["status"] == "SUBMITTED"
            assert resubmitted["resubmit_count"] == lap
        final = build.read_invoice(ctx["invoice"]["id"])
        assert final["status"] == "SUBMITTED"
        assert final["resubmit_count"] == 3
        assert final["amount_cents"] == 105_000

    def test_each_lap_replaces_the_paper_and_clears_both_stamps(self, api, build):
        """PRD 3.6: "both `amount_cents` and `documentation_ref` must be supplied and they replace the recorded values, `resubmit_count` increases by 1, and `dispute_reason` and `verified_by_user_id` are both cleared to null."

        Design: Corner/state_machines/vendor_invoice_cycles_submitted_verified_disputed_submitted_three_times
        """
        ctx = confirmed_show_with_a_submitted_invoice(build)
        for lap in (1, 2, 3):
            verified, disputed, resubmitted = cycle_invoice(
                api, build, ctx["invoice"]["id"], lap
            )
            assert verified["verified_by_user_id"] == f"u-acct-verifier-{lap}"
            assert disputed["verified_by_user_id"] is None
            assert disputed["dispute_reason"] == (
                f"lap {lap} packet page does not match the vendor total"
            )
            assert resubmitted["amount_cents"] == RESUBMIT_AMOUNTS[lap]
            assert resubmitted["documentation_ref"] == f"INV-LAP-{lap}"
            assert resubmitted["dispute_reason"] is None
            assert resubmitted["verified_by_user_id"] is None

    def test_the_line_ledger_stays_still_until_an_invoice_is_approved(
        self, api, build
    ):
        """PRD 3.6: "the line's `actual_cents` is refreshed to the total `amount_cents` of the line's invoices whose status is `APPROVED` — only `APPROVED` invoices count, so `SUBMITTED`, `VERIFIED`, `DISPUTED` and `REJECTED` amounts are all excluded"

        Design: Corner/state_machines/vendor_invoice_cycles_submitted_verified_disputed_submitted_three_times
        """
        ctx = confirmed_show_with_a_submitted_invoice(build)
        for lap in (1, 2, 3):
            cycle_invoice(api, build, ctx["invoice"]["id"], lap)

        mid_cycle_line = build.read_budget_line(ctx["line"]["id"])
        assert mid_cycle_line["actual_cents"] == 0
        assert mid_cycle_line["settlement_expense_cents"] == 0
        assert mid_cycle_line["status"] == "ACTIVE"
        assert build.read_show(ctx["show"]["id"])["total_actual_expense_cents"] == 0

        validate_success(
            api.verify_vendor_invoice(
                ctx["invoice"]["id"], make_tour_accountant_headers("u-acct-verifier-4")
            )
        )
        approved = validate_success(
            api.approve_vendor_invoice(
                ctx["invoice"]["id"], make_tour_accountant_headers("u-acct-approver")
            )
        )
        assert approved["status"] == "APPROVED"
        assert approved["approved_by_user_id"] == "u-acct-approver"

        line = build.read_budget_line(ctx["line"]["id"])
        assert line["actual_cents"] == 105_000
        assert line["variance_cents"] == 5_000
        assert float(line["variance_pct"]) == 5.00
        assert line["variance_status"] == "WITHIN_TOLERANCE"
        assert line["required_approver_role"] == "NONE"
        assert line["settlement_expense_cents"] == 105_000
        show = build.read_show(ctx["show"]["id"])
        assert show["total_actual_expense_cents"] == 105_000
        assert show["total_budgeted_expense_cents"] == 100_000
        assert show["budget_posture"] == "ON_BUDGET"

    def test_an_approved_invoice_leaves_the_cycle_for_good(self, api, build):
        """PRD 3.6: "Approval — available to a `TourAccountant` or a `RiskOfficer` — moves it `VERIFIED → APPROVED` and records `approved_by_user_id`, and requires an acting `X-User-ID` different from the recorded `verified_by_user_id` (see §2.8), the line still `ACTIVE`, and the show still in one of those same three lifecycle states. `APPROVED` is terminal."

        Design: Corner/state_machines/vendor_invoice_cycles_submitted_verified_disputed_submitted_three_times
        """
        ctx = confirmed_show_with_a_submitted_invoice(build)
        for lap in (1, 2, 3):
            cycle_invoice(api, build, ctx["invoice"]["id"], lap)
        validate_success(
            api.verify_vendor_invoice(
                ctx["invoice"]["id"], make_tour_accountant_headers("u-acct-verifier-4")
            )
        )
        validate_success(
            api.approve_vendor_invoice(
                ctx["invoice"]["id"], make_tour_accountant_headers("u-acct-approver")
            )
        )
        validate_error(
            api.dispute_vendor_invoice(
                ctx["invoice"]["id"],
                build.accountant,
                dispute_reason="a fourth lap after the approval landed",
            ),
            E.ERR_ALREADY_TERMINAL,
        )
        invoice = build.read_invoice(ctx["invoice"]["id"])
        assert invoice["status"] == "APPROVED"
        assert invoice["resubmit_count"] == 3
        assert build.read_budget_line(ctx["line"]["id"])["actual_cents"] == 105_000
