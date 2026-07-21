"""Table holds and their turnover buffer, ticket pricing, capacity and seating."""
from test_helpers import (
    TEST_DEFAULTS,
    TEST_USERS,
    ApiErrorId,
    assert_ticket_order,
    buy_ticket_order,
    cancel_ticket_order,
    create_bidder_payload,
    create_table_hold_payload,
    create_ticket_order_payload,
    make_bidder_headers,
    place_hold,
    read_hold,
    read_table,
    read_ticket_order,
    set_clock,
    setup_published_event,
    validate_error,
    validate_success,
)


class TestTableHoldTurnoverBuffer:
    """PRD §3.2's fifteen-minute clearance between holds on the same table."""

    def test_hold_ten_minutes_after_incumbent_conflicts(self, api):
        """PRD §3.2: "A proposed hold conflicts with an existing `HELD` hold on
        that same table exactly when the new hold's start falls before the
        existing hold's end plus fifteen minutes *and* the existing hold's start
        falls before the new hold's end plus fifteen minutes; when both of those
        are true the request is refused with `ERR_TABLE_HOLD_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/table_hold_buffer_accepts_exactly_fifteen_minute_gap
        """
        env = setup_published_event(bidder_count=2)
        table_id = env["table"]["id"]
        guest_a, guest_b = env["bidders"]
        incumbent = place_hold(
            table_id,
            guest_a["id"],
            hold_start_utc="2026-07-05T18:00:00Z",
            hold_end_utc="2026-07-05T20:00:00Z",
        )

        response = api.create_table_hold(
            create_table_hold_payload(
                table_id,
                guest_b["id"],
                hold_start_utc="2026-07-05T20:10:00Z",
                hold_end_utc="2026-07-05T21:00:00Z",
            ),
            TEST_USERS["organizer_headers"],
        )

        validate_error(response, ApiErrorId.ERR_TABLE_HOLD_CONFLICT.value, 409)
        assert read_hold(incumbent["id"])["status"] == "HELD", (
            "The incumbent hold is untouched by a refused proposal"
        )

    def test_hold_exactly_fifteen_minutes_after_incumbent_is_accepted(self, api):
        """PRD §3.2: "The comparison is strict on both sides, so two holds
        separated by exactly fifteen minutes of clearance are accepted."
        PRD §3.2: "A hold starts in `HELD` and may end in either `CONSUMED` or
        `RELEASED`, both terminal."

        Design: Difficulty/resource_temporal_overlap/table_hold_buffer_accepts_exactly_fifteen_minute_gap
        """
        env = setup_published_event(bidder_count=2)
        table_id = env["table"]["id"]
        guest_a, guest_b = env["bidders"]
        place_hold(
            table_id,
            guest_a["id"],
            hold_start_utc="2026-07-05T18:00:00Z",
            hold_end_utc="2026-07-05T20:00:00Z",
        )

        response = api.create_table_hold(
            create_table_hold_payload(
                table_id,
                guest_b["id"],
                hold_start_utc="2026-07-05T20:15:00Z",
                hold_end_utc="2026-07-05T21:00:00Z",
            ),
            TEST_USERS["organizer_headers"],
        )
        hold = validate_success(response, 201)

        assert hold["status"] == "HELD", (
            f"Exactly fifteen minutes of clearance is accepted, got {hold['status']}"
        )
        assert read_table(table_id)["seats_reserved"] == 0, (
            "A soft hold consumes no seats"
        )


def test_unpublish_releases_every_held_hold(api):
    """PRD §3.1: "Reverting the event cascades: every table hold whose table
    belongs to this event and whose `status` is `HELD` moves to `RELEASED`,
    each released hold's table then recomputes its `seats_reserved` tally and
    its `status`, and the event's own `version` advances."

    Design: Corner/state_machines/unpublish_releases_every_held_table_hold
    """
    env = setup_published_event(bidder_count=1)
    guest = env["bidders"][0]
    hold = place_hold(env["table"]["id"], guest["id"])

    response = api.unpublish_event(env["event"]["id"], TEST_USERS["organizer_headers"])
    event = validate_success(response, 200)

    assert event["status"] == "DRAFT", f"Unpublish returns the event to DRAFT, got {event['status']}"
    assert read_hold(hold["id"])["status"] == "RELEASED", (
        "The HELD hold must be released by the unpublish cascade"
    )
    assert read_table(env["table"]["id"])["seats_reserved"] == 0


class TestEarlyBirdTicketPricing:
    """PRD §3.3's five pricing steps, with rounding pinned at the per-unit step."""

    def test_early_bird_seat_price_rounds_per_unit_before_multiplying(self, api):
        """PRD §3.3: "Fourth — and this ordering is pinned, not incidental — the
        per-unit price is computed first by multiplying the base price by one
        minus the discount rate and rounding that product half up to a whole
        cent, giving `unit_price_cents`; only then is `subtotal_cents` obtained
        by multiplying `unit_price_cents` by the unit count."
        PRD §3.3: "Third, the discount rate is zero for any order that is not
        early-bird eligible, fifteen percent for an early-bird `TABLE` order,
        and ten percent for an early-bird `SEAT` order."

        Design: Difficulty/combinatorial_formula/ticket_order_rounds_per_unit_before_multiplying
        """
        env = setup_published_event(bidder_count=1)
        guest = env["bidders"][0]

        response = api.create_ticket_order(
            create_ticket_order_payload(
                env["event"]["id"], guest["id"], env["table"]["id"],
                order_type="SEAT", seat_count=3,
            ),
            make_bidder_headers(guest["id"]),
        )
        order = validate_success(response, 201)

        assert_ticket_order(order)
        assert order["unit_price_cents"] == 11_280, (
            "12533 discounted ten percent rounds half up to 11280 per seat, got "
            f"{order['unit_price_cents']}"
        )
        assert order["subtotal_cents"] == 33_840, (
            "11280 times three seats is 33840 — not the 33839 a round-at-the-end "
            f"order of operations would give; got {order['subtotal_cents']}"
        )

    def test_early_bird_seat_order_records_benefit_and_reserves_seats(self, api):
        """PRD §3.3: "First, the early-bird cutoff is the event's
        `event_start_utc` less 30 days; the order is early-bird eligible, and
        `early_bird_applied` is set true, exactly when the logical clock is at
        or before that cutoff instant — the boundary is inclusive, so an order
        priced at the cutoff to the millisecond still earns the discount."
        PRD §3.3: "Fifth, `benefit_value_cents` records the non-deductible
        dinner benefit as 7,500 cents per seat multiplied by the order's
        `seat_count`."

        Design: Difficulty/combinatorial_formula/ticket_order_rounds_per_unit_before_multiplying
        """
        env = setup_published_event(bidder_count=1)
        guest = env["bidders"][0]

        order = buy_ticket_order(
            env["event"]["id"], guest["id"], env["table"]["id"],
            order_type="SEAT", seat_count=3,
        )

        assert order["early_bird_applied"] is True, (
            "A clock at 2026-07-05 precedes the 2026-08-13T23:00Z cutoff"
        )
        assert order["benefit_value_cents"] == 22_500, (
            f"7500 cents per seat over three seats is 22500, got "
            f"{order['benefit_value_cents']}"
        )
        assert read_table(env["table"]["id"])["seats_reserved"] == 3, (
            "Order creation reserves the seats on the table"
        )


def test_ticket_priced_after_early_bird_cutoff_gets_no_discount(api):
    """PRD §3.3: "Third, the discount rate is zero for any order that is not
    early-bird eligible, fifteen percent for an early-bird `TABLE` order, and
    ten percent for an early-bird `SEAT` order."
    PRD §3.3: "Second, the base price and unit count follow the order type: a
    `TABLE` order takes the table's `table_price_cents` as its base with a unit
    count of one, while a `SEAT` order takes the table's `seat_price_cents` as
    its base with a unit count equal to the order's `seat_count`."

    Design: Corner/calculations/ticket_priced_after_early_bird_cutoff_gets_no_discount
    """
    env = setup_published_event(bidder_count=1)
    guest = env["bidders"][0]
    set_clock(TEST_DEFAULTS["POST_CUTOFF_CLOCK_UTC"])

    order = buy_ticket_order(
        env["event"]["id"], guest["id"], env["table"]["id"],
        order_type="SEAT", seat_count=3,
    )

    assert order["early_bird_applied"] is False, (
        "A clock past the cutoff earns no early-bird discount"
    )
    assert order["unit_price_cents"] == 12_533, (
        f"The undiscounted seat price is 12533, got {order['unit_price_cents']}"
    )
    assert order["subtotal_cents"] == 37_599, (
        f"12533 times three seats is 37599, got {order['subtotal_cents']}"
    )
    assert order["payment_status"] == "UNBILLED"
    assert order["seating_status"] == "UNSEATED"


def test_seat_order_beyond_table_capacity_is_refused(api):
    """PRD §3.3: "A `TABLE` order buys the whole table and its `seat_count` must
    equal the table's own `seat_count` exactly; a mismatch, or any order that
    would push the table's `seats_reserved` plus the requested `seat_count`
    above the table's `seat_count`, is refused with
    `ERR_SEAT_CAPACITY_EXCEEDED`."

    Design: Corner/validations/seat_order_beyond_table_capacity_is_refused
    """
    env = setup_published_event(bidder_count=1)
    guest = env["bidders"][0]

    response = api.create_ticket_order(
        create_ticket_order_payload(
            env["event"]["id"], guest["id"], env["table"]["id"],
            order_type="SEAT", seat_count=11,
        ),
        make_bidder_headers(guest["id"]),
    )

    validate_error(response, ApiErrorId.ERR_SEAT_CAPACITY_EXCEEDED.value, 409)
    table = read_table(env["table"]["id"])
    assert table["seats_reserved"] == 0, "A refused order reserves nothing"
    assert table["status"] == "AVAILABLE"


def test_duplicate_paddle_number_within_event_is_refused(api):
    """PRD §3.3: "An `EventOrganizer` registers a `Bidder` against an event by
    supplying `event_id`, the `display_name` printed on the bid sheet, a
    contact `email` for receipts, and a `paddle_number` of at least 1 that must
    be unique among the guests of that event — a collision is refused with
    `ERR_DUPLICATE_PADDLE_NUMBER`."

    Design: Corner/validations/duplicate_paddle_number_within_event_is_refused
    """
    env = setup_published_event(bidder_count=1)
    guest_a = env["bidders"][0]

    response = api.create_bidder(
        create_bidder_payload(
            env["event"]["id"],
            display_name="Imposter",
            email="imp@example.org",
            paddle_number=guest_a["paddle_number"],
        ),
        TEST_USERS["organizer_headers"],
    )

    validate_error(response, ApiErrorId.ERR_DUPLICATE_PADDLE_NUMBER.value, 409)
    assert guest_a["paddle_number"] == 101


class TestTicketOrderCancellation:
    """PRD §3.3's cancellation, which moves both axes and returns inventory."""

    def test_cancel_ticket_order_drives_both_axes_terminal(self, api):
        """PRD §3.3: "Cancellation is an organizer action that drives
        `payment_status` to `REFUNDED` from either `UNBILLED` or `PAID`, sets
        `seating_status` to `RELEASED`, causes the order's table to recompute
        `seats_reserved` — which decreases by that order's `seat_count` — and
        its `status`, and advances the order's `version`."

        Design: Difficulty/compensating_invariant/ticket_order_cancel_restores_table_seat_inventory
        """
        env = setup_published_event(bidder_count=1)
        guest = env["bidders"][0]
        order = buy_ticket_order(
            env["event"]["id"], guest["id"], env["table"]["id"],
            order_type="SEAT", seat_count=3,
        )
        assert order["subtotal_cents"] == 33_840

        response = api.cancel_ticket_order(
            order["id"], TEST_USERS["organizer_headers"]
        )
        cancelled = validate_success(response, 200)

        assert cancelled["payment_status"] == "REFUNDED", (
            f"Cancellation refunds the billing axis, got {cancelled['payment_status']}"
        )
        assert cancelled["seating_status"] == "RELEASED", (
            f"Cancellation releases the seating axis, got {cancelled['seating_status']}"
        )

    def test_cancel_ticket_order_returns_seat_inventory_to_zero(self, api):
        """PRD §3.2: "A table tracks `seats_reserved`, the number of seats
        consumed by ticket orders of that table whose `payment_status` is
        anything other than `REFUNDED` and whose `seating_status` is anything
        other than `RELEASED`. Its `status` is derived from that tally:
        `AVAILABLE` while `seats_reserved` is strictly below `seat_count`, and
        `SOLD_OUT` once the two are equal."

        Design: Difficulty/compensating_invariant/ticket_order_cancel_restores_table_seat_inventory
        """
        env = setup_published_event(bidder_count=1)
        guest = env["bidders"][0]
        table_id = env["table"]["id"]
        order = buy_ticket_order(
            env["event"]["id"], guest["id"], table_id,
            order_type="SEAT", seat_count=3,
        )
        assert read_table(table_id)["seats_reserved"] == 3, (
            "Three seats are consumed before the compensating cancel"
        )

        cancel_ticket_order(order["id"])

        table = read_table(table_id)
        assert table["seats_reserved"] == 0, (
            f"Cancelling the only order returns the tally to 0, got "
            f"{table['seats_reserved']}"
        )
        assert table["status"] == "AVAILABLE"
        assert read_ticket_order(order["id"])["payment_status"] == "REFUNDED"
