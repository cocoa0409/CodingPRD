"""Box-office pricing order, the seats-before-sales-window ladder, and seat conservation.

The canonical house sells 8 of its 12 seats: 4 are house hold seats that are
permanently withheld, so every rollup in this file must add back to 12.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_order_pricing,
    assert_seat_conservation,
    assert_showtime,
    assert_ticket_order,
    close_engagement,
    close_showtime_sales,
    open_showtime_sales,
    place_showtime,
    read_booking,
    read_order,
    read_showtime,
    refund_order,
    sell_seats,
    setup_member_at_tier,
    setup_programming_baseline,
    setup_screening_on_sale,
    setup_sold_out_screening,
    ticket_order_payload,
    validate_error,
    validate_paginated,
)


class TestPerTicketRoundingBeforeSummation:
    """Rounding happens once per ticket, never once per line."""

    def test_member_order_rounds_each_ticket_before_multiplying(self):
        """Three seats at 1450 less 0.15 price at 1233 each, not 1232.5 summed.

        PRD: "Discounting the whole line and rounding once at the end is explicitly wrong: at a base price of 1450 cents with a 0.15 discount over three paid seats, the correct figures round each ticket to 1233 cents for a subtotal of 3699 cents, where rounding after multiplication would yield one cent less."

        Design: Difficulty/combinatorial_formula/ticket_pricing_per_ticket_rounding_before_summation
        """
        world = setup_screening_on_sale("2026-08-14T12:00:00Z")
        member = setup_member_at_tier("SUPPORTER")
        assert member["discount_pct"] == 0.15

        order = sell_seats(
            world["showtime"]["id"],
            3,
            purchaser_email="ada@example.com",
            member_id=member["id"],
        )

        assert_ticket_order(order)
        assert order["status"] == "RESERVED"
        assert_order_pricing(order, 1233, 3699, 450, 4149)
        assert order["total_cents"] != 4148, "rounding after multiplication is wrong"

    def test_member_order_moves_the_seat_rollup_as_it_prices(self):
        """The reserved order takes three of the eight sellable seats.

        PRD: "Sixth `facility_fee_cents` is 150 cents per seat multiplied by the order's full `quantity` — comp seats pay the facility fee too — and the fee is retained by the cinema rather than shared with the distributor."

        Design: Difficulty/combinatorial_formula/ticket_pricing_per_ticket_rounding_before_summation
        """
        world = setup_screening_on_sale("2026-08-14T12:00:00Z")
        member = setup_member_at_tier("SUPPORTER")

        sell_seats(
            world["showtime"]["id"],
            3,
            purchaser_email="ada@example.com",
            member_id=member["id"],
        )

        showtime = read_showtime(world["showtime"]["id"])
        assert showtime["seats_sold"] == 3
        assert showtime["seats_available"] == 5
        assert showtime["sale_status"] == "ON_SALE"
        assert_seat_conservation(showtime, world["venue"])


class TestSeatsOutranksTheSalesWindow:
    """Rung 19 fires before rung 25, so an oversized order hides a closed window."""

    def test_oversized_order_on_a_closed_screening_reports_insufficient_seats(
        self, anonymous_headers
    ):
        """A sold-out, sales-closed screening answers with the seats error.

        PRD: "And because seats (19) outranks the comp allowance (20) and the sales-open check (25), an order for more seats than exist on a screening whose sales are closed is reported as `ERR_INSUFFICIENT_SEATS`."

        Design: Difficulty/priority_pair_validation_conflict/insufficient_seats_outranks_showtime_sales_closed
        """
        world = setup_sold_out_screening("2026-08-14T12:00:00Z")
        assert world["showtime"]["sale_status"] == "SOLD_OUT"
        closed = close_showtime_sales(world["showtime"]["id"])
        assert closed["sale_status"] == "SALES_CLOSED"

        response = api_client.create_ticket_order(
            ticket_order_payload(
                world["showtime"]["id"], 1, purchaser_email="latecomer@example.com"
            ),
            anonymous_headers,
        )

        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_SEATS)

    def test_refused_late_order_leaves_the_closed_screening_untouched(
        self, anonymous_headers, box_office_headers
    ):
        """Both paid orders survive and the screening keeps its full rollup.

        PRD: "The requested `quantity` must not exceed the screening's `seats_available`, otherwise `ERR_INSUFFICIENT_SEATS`."

        Design: Difficulty/priority_pair_validation_conflict/insufficient_seats_outranks_showtime_sales_closed
        """
        world = setup_sold_out_screening("2026-08-14T12:00:00Z")
        close_showtime_sales(world["showtime"]["id"])

        validate_error(
            api_client.create_ticket_order(
                ticket_order_payload(
                    world["showtime"]["id"], 1, purchaser_email="latecomer@example.com"
                ),
                anonymous_headers,
            ),
            ApiErrorId.ERR_INSUFFICIENT_SEATS,
        )

        showtime = read_showtime(world["showtime"]["id"])
        assert showtime["sale_status"] == "SALES_CLOSED"
        assert showtime["seats_sold"] == 8
        assert showtime["seats_available"] == 0
        assert_seat_conservation(showtime, world["venue"])

        rows, meta = validate_paginated(
            api_client.list_ticket_orders(
                box_office_headers, {"showtime_id": world["showtime"]["id"]}
            )
        )
        assert meta["total_count"] == 2, "the refusal minted no order"
        assert all(row["status"] == "PAID" for row in rows)


class TestSeatConservationAcrossSelloutAndRefund:
    """The 12-seat identity survives a sellout and the refund that undoes it."""

    def test_eight_paid_seats_drive_the_screening_to_sold_out(self):
        """Two four-seat paid orders leave zero available and flip the sale dimension.

        PRD: "Between opening and closing, the sale dimension oscillates on its own: the moment an order drives `seats_available` to exactly 0 the screening moves `ON_SALE → SOLD_OUT`, and the moment a refund or a void frees at least one seat again it moves `SOLD_OUT → ON_SALE`."

        Design: Difficulty/compensating_invariant/seat_conservation_survives_sellout_then_refund
        """
        world = setup_sold_out_screening("2026-08-14T12:00:00Z")

        showtime = read_showtime(world["showtime"]["id"])
        assert_showtime(showtime)
        assert showtime["sale_status"] == "SOLD_OUT"
        assert showtime["seats_sold"] == 8
        assert showtime["seats_available"] == 0
        assert showtime["gross_cents"] == 12800
        assert showtime["admissions_count"] == 8
        assert_seat_conservation(showtime, world["venue"])

    def test_cash_refund_frees_four_seats_and_reopens_the_screening(self):
        """Refunding the first order rolls the screening back to four sold.

        PRD: "The order moves `PAID → REFUNDED`, the screening's `gross_cents` falls by the order's `total_cents`, its `admissions_count` and `seats_sold` both fall by the order's `quantity`, and the screening flips `SOLD_OUT → ON_SALE` once at least one seat is free again."

        Design: Difficulty/compensating_invariant/seat_conservation_survives_sellout_then_refund
        """
        world = setup_sold_out_screening("2026-08-14T12:00:00Z")
        first_order = world["orders"][0]

        refunded = refund_order(first_order["id"], "CASH")

        assert refunded["status"] == "REFUNDED"
        assert refunded["refund_destination"] == "CASH"

        showtime = read_showtime(world["showtime"]["id"])
        assert showtime["sale_status"] == "ON_SALE"
        assert showtime["seats_sold"] == 4
        assert showtime["seats_available"] == 4
        assert showtime["gross_cents"] == 6400
        assert showtime["admissions_count"] == 4
        assert_seat_conservation(showtime, world["venue"])

    def test_house_hold_seats_and_the_surviving_order_are_untouched_by_the_refund(self):
        """Four seats stay permanently withheld and the second order keeps its money.

        PRD: "After every mutation, including every cascade, the identity holds that `seats_sold` plus `seats_available` plus the venue's `house_hold_seats` equals the venue's `seat_capacity` — the house hold seats are permanently withheld from sale and are never sellable."

        Design: Difficulty/compensating_invariant/seat_conservation_survives_sellout_then_refund
        """
        world = setup_sold_out_screening("2026-08-14T12:00:00Z")

        refund_order(world["orders"][0]["id"], "CASH")

        survivor = read_order(world["orders"][1]["id"])
        assert survivor["status"] == "PAID"
        assert survivor["total_cents"] == 6400
        assert survivor["refund_destination"] is None

        showtime = read_showtime(world["showtime"]["id"])
        assert world["venue"]["house_hold_seats"] == 4
        assert world["venue"]["seat_capacity"] == 12
        assert showtime["seats_sold"] + showtime["seats_available"] == 8, (
            "only eight of the twelve seats are ever sellable"
        )
        assert_seat_conservation(showtime, world["venue"])


class TestOpenSalesReadsTheOwningEngagement:
    """Opening sales looks past the screening at the engagement that owns it."""

    def test_open_sales_refused_while_the_owning_engagement_is_closed(
        self, box_office_headers
    ):
        """A perfectly DRAFT, SCHEDULED screening cannot open under a CLOSED engagement.

        PRD: "A `BoxOfficeManager` puts a screening on sale, moving `sale_status` `DRAFT → ON_SALE`; this requires the screening's status to be `SCHEDULED` and its `sale_status` to be `DRAFT`, otherwise `ERR_SHOWTIME_INVALID_STATE`, requires the owning engagement to be `CONFIRMED` or `RUNNING`, otherwise `ERR_DEPENDENCY_STATE_INVALID`, and requires at least one seat to be available, otherwise `ERR_INSUFFICIENT_SEATS`."

        Design: Difficulty/cross_entity_state_dependency/open_sales_reads_owning_booking_state_not_showtime_state
        """
        world = setup_programming_baseline()
        first = place_showtime(world, "2026-08-14T12:00:00Z")
        second = place_showtime(world, "2026-08-15T12:00:00Z")
        open_showtime_sales(first["id"])
        close_engagement(world["booking"]["id"])

        pending = read_showtime(second["id"])
        assert pending["status"] == "SCHEDULED"
        assert pending["sale_status"] == "DRAFT"

        response = api_client.open_sales(second["id"], box_office_headers)

        validate_error(response, ApiErrorId.ERR_DEPENDENCY_STATE_INVALID)

    def test_refused_open_sales_leaves_both_screenings_and_the_engagement_intact(
        self, box_office_headers
    ):
        """The already-open sibling keeps selling and the blocked screening stays DRAFT.

        PRD: "Dependency state — the booth test requires an ingested package and opening sales requires a confirmed or running engagement (`ERR_DEPENDENCY_STATE_INVALID`). Applies to the booth playback test and to opening sales."

        Design: Difficulty/cross_entity_state_dependency/open_sales_reads_owning_booking_state_not_showtime_state
        """
        world = setup_programming_baseline()
        first = place_showtime(world, "2026-08-14T12:00:00Z")
        second = place_showtime(world, "2026-08-15T12:00:00Z")
        open_showtime_sales(first["id"])
        close_engagement(world["booking"]["id"])

        validate_error(
            api_client.open_sales(second["id"], box_office_headers),
            ApiErrorId.ERR_DEPENDENCY_STATE_INVALID,
        )

        blocked = read_showtime(second["id"])
        assert blocked["sale_status"] == "DRAFT", "the refusal opened nothing"
        assert blocked["status"] == "SCHEDULED"
        assert blocked["seats_available"] == 8
        assert_seat_conservation(blocked, world["venue"])

        opened = read_showtime(first["id"])
        assert opened["sale_status"] == "ON_SALE", "the sibling window is unaffected"

        booking = read_booking(world["booking"]["id"])
        assert booking["status"] == "CLOSED"
        assert booking["scheduled_showtime_count"] == 2
