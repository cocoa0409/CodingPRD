"""Ticket pricing, the box-office rollup, settlement figures and the optimiser.

Money in this service is computed in a normative order and the aggregates are
always rebuilt from the surviving source rows. These tests pin the arithmetic on
a single admitted order, on a rollup that has just lost an unpaid hold, on the
two settlement inclusion sets, and on an optimiser search whose candidate pool
is emptied by an existing screen block.
"""
from test_helpers import (
    ANONYMOUS,
    BOX_OFFICE,
    BOX_OFFICE_USER_ID,
    EXECUTIVE_DIRECTOR,
    EXECUTIVE_DIRECTOR_USER_ID,
    PROGRAMMER,
    ApiErrorId,
    api_client,
    assert_order_pricing,
    assert_seat_conservation,
    assert_settlement,
    assert_ticket_order,
    auto_schedule_payload,
    booking_version,
    clearance_version,
    close_engagement,
    close_showtime_sales,
    draft_settlement,
    make_member_headers,
    pay_for_order,
    read_clearance,
    read_member,
    read_order,
    read_settlement,
    read_showtime,
    sell_seats,
    setup_closed_engagement,
    setup_member_at_tier,
    setup_scheduled_screening,
    setup_screening_on_sale,
    settlement_payload,
    submit_settlement,
    ticket_order_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTicketPricing:
    """The nine pricing steps, on a walk-up order and on a comped member order."""

    def test_anonymous_purchase_of_four_seats_prices_and_holds_them(self):
        """A walk-up order takes no discount and holds its seats before payment.

        PRD: "First the gross unit price is the screening's `base_price_cents` plus its
        `surcharge_cents`, the latter being non-zero only while a `CONFIRMED` special
        event is attached."

        PRD: "Third the applicable discount is 0.00 when the order carries no
        `member_id`, and otherwise the member's `discount_pct`."

        PRD: "An admitted order is created in `RESERVED` with a null
        `refund_destination`, and it moves the ledgers immediately: the member's
        `credit_balance_cents` falls by `applied_credit_cents`, the member's
        `comp_tickets_remaining` falls by `comp_quantity`, the screening's `seats_sold`
        rises by `quantity`, `seats_available` is recomputed, and the screening flips
        `ON_SALE → SOLD_OUT` if that lands on exactly zero."

        Design: Corner/calculations/ticket_order_pricing_correct_result_for_an_anonymous_purchase
        """
        world = setup_screening_on_sale("2026-08-14T12:00:00Z")

        response = api_client.create_ticket_order(
            ticket_order_payload(world["showtime"]["id"], 4), ANONYMOUS
        )
        order = validate_success(response, expected_status=201)

        assert order["status"] == "RESERVED"
        assert order["quantity"] == 4
        assert order["comp_quantity"] == 0, "comp_quantity defaults to 0 when omitted"
        assert order["member_id"] is None, "a walk-up order carries no member"
        assert order["refund_destination"] is None
        assert_order_pricing(
            order,
            unit_price_cents=1450,
            line_subtotal_cents=5800,
            facility_fee_cents=600,
            total_cents=6400,
            applied_credit_cents=0,
        )
        assert_ticket_order(order)

        showtime = read_showtime(world["showtime"]["id"])
        assert showtime["seats_sold"] == 4, "the hold moved the seat ledger at once"
        assert showtime["seats_available"] == 4
        assert showtime["gross_cents"] == 0, "an unpaid hold contributes no gross"
        assert showtime["admissions_count"] == 0
        assert showtime["sale_status"] == "ON_SALE", "four of eight seats remain"
        assert_seat_conservation(showtime, world["venue"])

    def test_comp_seats_still_pay_the_facility_fee(self):
        """A supporter's comped seat is free of admission but not of the facility fee.

        PRD: "Fourth — and this is the step that must not be reordered —
        `unit_price_cents` is the gross unit price multiplied by one minus the discount,
        **rounded half up to a whole cent at this point, per ticket, before any
        multiplication**."

        PRD: "Sixth `facility_fee_cents` is 150 cents per seat multiplied by the order's
        full `quantity` — comp seats pay the facility fee too — and the fee is retained
        by the cinema rather than shared with the distributor."

        Design: Corner/calculations/facility_fee_constant_is_charged_on_comp_tickets_too
        """
        world = setup_screening_on_sale("2026-08-14T12:00:00Z")
        member = setup_member_at_tier("SUPPORTER")
        assert member["effective_tier"] == "SUPPORTER"
        assert member["discount_pct"] == 0.15
        assert member["comp_tickets_granted"] == 2

        payload = ticket_order_payload(
            world["showtime"]["id"],
            3,
            member_id=member["id"],
            comp_quantity=1,
            purchaser_email="ada@example.com",
        )
        response = api_client.create_ticket_order(
            payload, make_member_headers(member["id"])
        )
        order = validate_success(response, expected_status=201)

        assert order["status"] == "RESERVED"
        assert order["comp_quantity"] == 1
        # Two paid seats at 1233 each, but the fee is charged on all three.
        assert_order_pricing(
            order,
            unit_price_cents=1233,
            line_subtotal_cents=2466,
            facility_fee_cents=450,
            total_cents=2916,
        )
        assert order["total_cents"] != 2766, (
            "charging the fee on paid seats only would understate the order by 150 cents"
        )
        assert_ticket_order(order)

        after = read_member(member["id"])
        assert after["comp_tickets_granted"] == 2
        assert after["comp_tickets_remaining"] == 1, "the held comp is spent"

        showtime = read_showtime(world["showtime"]["id"])
        assert showtime["seats_sold"] == 3, "comps occupy seats like any other"
        assert_seat_conservation(showtime, world["venue"])


class TestBoxOfficeRollup:
    """The four rollup figures are rebuilt from the orders that survive."""

    def test_closing_the_box_office_drops_the_voided_hold_from_the_rollup(self):
        """A paid order and an unpaid hold; closing keeps only the paid one.

        PRD: "Closing the box office for a screening moves `sale_status` from `ON_SALE`
        or `SOLD_OUT` to `SALES_CLOSED` and releases every unpaid hold: every order on
        the screening whose status is `RESERVED` becomes `VOID`, and the screening's
        rollup is recomputed from what survives."

        PRD: "A screening's `seats_sold` is the sum of `quantity` across its orders whose
        status is reserved or paid; its `seats_available` is the venue's `seat_capacity`
        less the venue's `house_hold_seats` less `seats_sold`, and never falls below zero;
        its `gross_cents` is the sum of `total_cents` across its paid orders and its
        `admissions_count` the sum of their `quantity`. Voided and refunded orders
        contribute to none of those four."

        Design: Corner/calculations/box_office_rollup_input_set_excludes_voided_holds
        """
        world = setup_screening_on_sale("2026-08-14T12:00:00Z")
        showtime_id = world["showtime"]["id"]

        paid = sell_seats(showtime_id, 3, headers=ANONYMOUS)
        pay_for_order(paid["id"])
        held = sell_seats(
            showtime_id, 2, headers=ANONYMOUS, purchaser_email="hold@example.com"
        )
        assert held["total_cents"] == 3200

        closed = close_showtime_sales(showtime_id)
        assert closed["sale_status"] == "SALES_CLOSED"

        surviving = read_order(paid["id"])
        assert surviving["status"] == "PAID"
        assert_order_pricing(
            surviving,
            unit_price_cents=1450,
            line_subtotal_cents=4350,
            facility_fee_cents=450,
            total_cents=4800,
        )

        released = read_order(held["id"])
        assert released["status"] == "VOID", "closing released the unpaid hold"
        assert released["total_cents"] == 3200, (
            "a voided order keeps its pinned price and simply stops counting"
        )

        showtime = read_showtime(showtime_id)
        assert showtime["seats_sold"] == 3, "only the paid order still holds seats"
        assert showtime["seats_available"] == 5
        assert showtime["gross_cents"] == 4800, "the voided hold contributes no gross"
        assert showtime["admissions_count"] == 3
        assert_seat_conservation(showtime, world["venue"])


class TestSettlementFigures:
    """The variant selects the inclusion set; finalising re-selects it."""

    def test_settlement_drafted_as_final_uses_the_final_inclusion_set(self):
        """A FINAL draft over a never-played engagement includes nothing at all.

        PRD: "Under `FINAL` — the figure actually remitted — the included screenings are
        only those whose status is `COMPLETED`, and the included orders only those whose
        status is `PAID`."

        PRD: "In all three cases `film_rent_cents` is the greater of that raw rent and
        the engagement's `guarantee_cents`: the guarantee is a **floor**, never a cap."

        PRD: "Drafting computes and stores every figure, copies the engagement's
        `min_run_penalty_cents` onto the settlement, creates the settlement in `DRAFT`
        with `submitted_by_user_id`, `finalized_by_user_id` and `dispute_note` all null,
        and increments the engagement's `version`."

        Design: Corner/calculations/settlement_variant_is_taken_from_the_posted_value_at_creation
        """
        world = setup_closed_engagement("2026-08-14T12:00:00Z")
        booking = world["booking"]
        assert booking["status"] == "CLOSED"
        assert booking["actual_playing_days"] == 0, "the screening never played"
        assert booking["min_run_penalty_cents"] == 6250

        response = api_client.create_settlement(
            settlement_payload(
                booking["id"], booking_version(booking["id"], BOX_OFFICE), "FINAL"
            ),
            BOX_OFFICE,
        )
        data = validate_success(response, expected_status=201)

        assert data["variant"] == "FINAL", "the posted variant is what is stored"
        assert data["status"] == "DRAFT"
        assert data["submitted_by_user_id"] is None
        assert data["finalized_by_user_id"] is None
        assert data["dispute_note"] is None

        assert data["box_office_cents"] == 0
        assert data["facility_fee_total_cents"] == 0
        assert data["adjusted_gross_cents"] == 0
        assert data["playing_days"] == 0, "no screening ever completed"
        assert data["proration_factor"] == 0.0
        assert data["house_nut_applied_cents"] == 0
        assert data["film_rent_cents"] == 3000, "the guarantee is the floor"
        assert data["cinema_retained_cents"] == -3000, (
            "the house owes the guarantee out of an empty gross"
        )
        assert data["min_run_penalty_cents"] == 6250, (
            "the penalty priced at closure is copied onto the settlement"
        )
        assert_settlement(data)

    def test_finalising_recomputes_every_figure_under_the_final_inclusion_set(self):
        """A provisional draft priced off an unpaid hold is rewritten by finalisation.

        PRD: "Under `PROVISIONAL` — the box office's forward-looking estimate at close —
        the included screenings are the engagement's screenings whose status is
        `SCHEDULED` or `COMPLETED`, and the included orders are those screenings' orders
        whose status is `RESERVED` or `PAID`."

        PRD: "Finalising is the `ExecutiveDirector`'s act from `SUBMITTED`: it recomputes
        **every** figure under the final inclusion set regardless of the variant the
        draft was created under, overwrites `variant` to `FINAL`, records
        `finalized_by_user_id` from the acting `X-User-ID`, and moves the settlement to
        `RECONCILED`."

        Design: Corner/calculations/finalize_switches_the_variant_and_recomputes_every_figure
        """
        world = setup_screening_on_sale("2026-08-14T12:00:00Z")
        hold = sell_seats(world["showtime"]["id"], 2, headers=ANONYMOUS)
        assert hold["status"] == "RESERVED"
        assert hold["total_cents"] == 3200
        assert hold["facility_fee_cents"] == 300

        booking = close_engagement(world["booking"]["id"])
        assert booking["status"] == "CLOSED"

        draft = draft_settlement(booking["id"], "PROVISIONAL")
        assert draft["variant"] == "PROVISIONAL"
        assert draft["box_office_cents"] == 3200, "the hold counts under PROVISIONAL"
        assert draft["facility_fee_total_cents"] == 300
        assert draft["adjusted_gross_cents"] == 2900
        assert draft["playing_days"] == 1, "the scheduled screening counts as a day"
        assert draft["proration_factor"] == 0.60, "one day of four, held up by the floor"
        assert draft["house_nut_applied_cents"] == 7500
        assert draft["film_rent_cents"] == 3000
        assert draft["cinema_retained_cents"] == 200
        assert draft["min_run_penalty_cents"] == 6250

        submitted = submit_settlement(draft["id"])
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_by_user_id"] == BOX_OFFICE_USER_ID

        response = api_client.finalize_settlement(draft["id"], EXECUTIVE_DIRECTOR)
        data = validate_success(response, expected_status=200)

        assert data["status"] == "RECONCILED"
        assert data["variant"] == "FINAL", "the variant is overwritten"
        assert data["box_office_cents"] == 0, "an unpaid hold is not remitted"
        assert data["facility_fee_total_cents"] == 0
        assert data["adjusted_gross_cents"] == 0
        assert data["playing_days"] == 0, "no screening ever completed"
        assert data["proration_factor"] == 0.0
        assert data["house_nut_applied_cents"] == 0
        assert data["film_rent_cents"] == 3000, "the guarantee is still the floor"
        assert data["cinema_retained_cents"] == -3000
        assert data["min_run_penalty_cents"] == 6250, "the penalty is retained"
        assert data["submitted_by_user_id"] == BOX_OFFICE_USER_ID, (
            "finalisation does not rewrite who submitted"
        )
        assert data["finalized_by_user_id"] == EXECUTIVE_DIRECTOR_USER_ID
        assert_settlement(data)

        assert read_settlement(draft["id"])["variant"] == "FINAL"
        assert read_order(hold["id"])["status"] == "RESERVED", (
            "settling does not touch the order it declined to count"
        )


class TestOptimiserCandidatePool:
    """When the grid is emptied by an existing block, nothing is created."""

    def test_auto_schedule_with_no_surviving_slot_is_refused(self):
        """A search window wholly inside an existing screen block yields no slot.

        PRD: "If no slot survives, nothing is created and the request is refused with
        `ERR_NO_ELIGIBLE_SLOT`."

        PRD: "Surviving slots are then scored, and the winner's score is stored on the
        created screening as `slot_score` — a field that is only ever populated by the
        optimiser and stays null on a hand-placed screening."

        Design: Corner/calculations/auto_schedule_with_no_surviving_candidate_returns_no_eligible_slot
        """
        world = setup_scheduled_screening("2026-08-14T12:00:00Z")
        standing = world["showtime"]
        # The standing screening occupies the screen from 12:00 to 14:21.
        assert standing["blocked_until"] == "2026-08-14T14:21:00.000Z"
        version_before = clearance_version(world["clearance"]["id"])

        payload = auto_schedule_payload(
            world["venue"]["id"],
            world["title"]["id"],
            world["booking"]["id"],
            world["clearance"]["id"],
            world["asset"]["id"],
            "2026-08-14",
            "12:00",
            "14:00",
            version_before,
        )
        response = api_client.auto_schedule_showtime(payload, PROGRAMMER)

        validate_error(
            response, ApiErrorId.ERR_NO_ELIGIBLE_SLOT.value, expected_status=422
        )

        rows, meta = validate_paginated(
            api_client.list_showtimes(
                PROGRAMMER, params={"venue_id": world["venue"]["id"]}
            )
        )
        assert meta["total_count"] == 1, "the failed search created no screening"
        assert rows[0]["id"] == standing["id"]

        clearance = read_clearance(world["clearance"]["id"])
        assert clearance["screenings_used"] == 1, "the failed search drew nothing down"
        assert clearance["screenings_remaining"] == 5
        assert clearance["version"] == version_before, (
            "the licence was not mutated by the refused search"
        )

        assert read_showtime(standing["id"])["slot_score"] is None, (
            "no score was written anywhere, least of all on the hand-placed screening"
        )
