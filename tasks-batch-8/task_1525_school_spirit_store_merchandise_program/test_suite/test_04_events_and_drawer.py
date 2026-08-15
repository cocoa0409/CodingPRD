"""Event register booking, drawer open/count, segregation, tolerance boundary."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_active_program,
    create_event,
    create_open_event,
    create_pos_order,
    make_cashier_headers,
    make_treasurer_headers,
    open_drawer,
    set_clock,
    setup_storefront,
    TEST_USERS,
    validate_error,
    validate_success,
)

DIRECTOR = TEST_USERS["director_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
TREASURER = TEST_USERS["treasurer_headers"]


class TestRegisterBookingBuffer:
    def test_exact_buffer_gap_allowed_and_one_minute_short_conflicts(self, api):
        """PRD §3.6: "Register discipline applies at booking: two events on
        the same `register_location` must keep a gap of at least the program's
        `register_buffer_minutes` between their windows, and the buffer rule
        treats the windows as the closed intervals they are, inclusive
        endpoints and all; a booking that lands within the buffer of an
        existing non-`CANCELLED` event on the same register is rejected with
        `ERR_EVENT_REGISTER_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/register_booking_buffer_gap
        """
        program = create_active_program()
        create_event(
            program["id"],
            register="GYM-A",
            name="JV Game",
            starts="2026-09-05T14:00:00Z",
            ends="2026-09-05T16:00:00Z",
        )
        exact = validate_success(
            api.create_event_sale(
                {
                    "program_id": program["id"],
                    "name": "Varsity Game",
                    "register_location": "GYM-A",
                    "starts_at": "2026-09-05T16:30:00Z",
                    "ends_at": "2026-09-05T18:00:00Z",
                },
                MANAGER,
            ),
            201,
        )
        assert exact["id"], (
            "start 16:30 exactly equals prior end 16:00 plus the 30-minute "
            "buffer; 'gap of at least' the buffer leaves it conflict-free"
        )

        short_res = api.create_event_sale(
            {
                "program_id": program["id"],
                "name": "Pep Rally",
                "register_location": "GYM-A",
                "starts_at": "2026-09-05T16:29:00Z",
                "ends_at": "2026-09-05T18:00:00Z",
            },
            MANAGER,
        )
        validate_error(short_res, ApiErrorId.ERR_EVENT_REGISTER_CONFLICT, 409)

    def test_buffer_rule_is_per_register(self, api):
        """PRD §3.6: "Register discipline applies at booking: two events on
        the same `register_location` must keep a gap of at least the program's
        `register_buffer_minutes` between their windows, and the buffer rule
        treats the windows as the closed intervals they are, inclusive
        endpoints and all; a booking that lands within the buffer of an
        existing non-`CANCELLED` event on the same register is rejected with
        `ERR_EVENT_REGISTER_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/register_booking_buffer_gap
        """
        program = create_active_program()
        create_event(
            program["id"],
            register="GYM-A",
            name="JV Game",
            starts="2026-09-05T14:00:00Z",
            ends="2026-09-05T16:00:00Z",
        )
        other_register = validate_success(
            api.create_event_sale(
                {
                    "program_id": program["id"],
                    "name": "Soccer",
                    "register_location": "FIELD-1",
                    "starts_at": "2026-09-05T15:00:00Z",
                    "ends_at": "2026-09-05T17:00:00Z",
                },
                MANAGER,
            ),
            201,
        )
        assert other_register["id"], (
            "the buffer rule is per-register; FIELD-1 is unaffected by "
            "GYM-A bookings"
        )


class TestDrawerOpenAndCount:
    def test_open_drawer_after_event_end_rejected(self, api):
        """PRD §3.6: "The event must still be `SCHEDULED`, and the logical
        clock must not have passed `ends_at` — a late open is
        `ERR_EVENT_WINDOW_PASSED`."

        Design: Corner/errors/open_drawer_after_event_end_rejected
        """
        program = create_active_program()
        event = create_event(
            program["id"],
            register="GYM-H",
            name="Morning Sale",
            starts="2026-08-01T00:00:00Z",
            ends="2026-08-01T02:00:00Z",
        )
        set_clock("2026-08-02T00:00:00Z")
        res = api.open_drawer(
            event["id"],
            {"opening_float_cents": 10000},
            make_cashier_headers("cashier-01"),
        )
        validate_error(res, ApiErrorId.ERR_EVENT_WINDOW_PASSED, 409)

    def test_segregation_counter_must_not_equal_opener(self, api):
        """PRD §3.7: "Segregation of duties is hard-coded: the counter may not
        be the opener, so if the request's `X-User-ID` equals the recorded
        `opened_by_user_id`, the count is refused with
        `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/validations/segregation_counter_must_not_equal_opener
        """
        program = create_active_program()
        event = create_open_event(
            program["id"], register="GYM-D", cashier_id="cashier-01"
        )
        res = api.close_count(
            event["id"],
            {"closing_counted_cents": 10000},
            make_treasurer_headers("cashier-01"),
        )
        validate_error(res, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

    def test_store_manager_cannot_count_drawer(self, api):
        """PRD §2.1: "A `Treasurer` counts drawers (and may never count a
        drawer they did not open — indeed may never count one they *did*
        open), issues refunds, decides exchanges, and runs allocations."
        PRD §2.8: "The role is permitted for the endpoint, including the
        customer-ownership rule of §2.1, else `ERR_UNAUTHORIZED_ROLE`."

        Design: Corner/rbac/store_manager_cannot_count_drawer
        """
        program = create_active_program()
        event = create_open_event(program["id"], register="GYM-M")
        res = api.close_count(
            event["id"], {"closing_counted_cents": 10000}, MANAGER
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

    def test_reconciled_event_is_terminal(self, api):
        """PRD §3.7: "A valid count — accepted from `OPEN` or from `FLAGGED` —
        records `closing_counted_cents` and `counted_by_user_id`, moves the
        event through `COUNTED`, and computes `over_short_cents`: the counted
        cash minus the expected drawer, where the expected drawer is
        `opening_float_cents` plus `cash_sales_cents` minus
        `cash_refunds_cents`."
        PRD §3.6: "a manager may cancel it only from there — an opened event
        must be counted, not cancelled, and cancelling from any other state is
        `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/reconciled_event_is_terminal
        """
        program = create_active_program()
        event = create_open_event(program["id"], register="GYM-T")
        counted = validate_success(
            api.close_count(
                event["id"],
                {"closing_counted_cents": 10000},
                make_treasurer_headers("treas-01"),
            ),
            200,
        )
        assert counted["status"] == "RECONCILED", (
            "over_short 0 is within tolerance, so the event continues "
            "straight to RECONCILED"
        )

        recount = api.close_count(
            event["id"],
            {"closing_counted_cents": 10000},
            make_treasurer_headers("treas-01"),
        )
        validate_error(recount, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)
        cancel = api.cancel_event(event["id"], MANAGER)
        validate_error(cancel, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)


class TestOverShortToleranceBoundary:
    def _setup_counted_event(self, api):
        """Stocked variant + OPEN event (float 10000) + one CASH sale 2500.

        Expected drawer is 12500 = 10000 + 2500 - 0.
        """
        shop = setup_storefront(stock_qty=25)
        program_id = shop["program"]["id"]
        event = create_open_event(program_id, register="GYM-B")
        create_pos_order(
            program_id, event["id"], shop["variant"]["id"], 1, payment_method="CASH"
        )
        return event

    def test_over_short_exactly_at_tolerance_reconciles(self, api):
        """PRD §3.7: "If the absolute value of `over_short_cents` is at or
        below the program's `over_short_tolerance_cents` — a discrepancy
        exactly equal to the tolerance passes — the event continues straight
        from `COUNTED` to `RECONCILED`."
        PRD §3.7: "computes `over_short_cents`: the counted cash minus the
        expected drawer, where the expected drawer is `opening_float_cents`
        plus `cash_sales_cents` minus `cash_refunds_cents`."

        Design: Difficulty/boundary_precision_check/over_short_exactly_at_tolerance_reconciles
        """
        event = self._setup_counted_event(api)
        res = validate_success(
            api.close_count(
                event["id"],
                {"closing_counted_cents": 13000},
                make_treasurer_headers("treas-01"),
            ),
            200,
        )
        assert res["over_short_cents"] == 500, (
            f"13000 - (10000 + 2500 - 0) == 500, got {res['over_short_cents']}"
        )
        assert res["status"] == "RECONCILED", (
            "|500| <= 500 tolerance: exactly at the boundary reconciles"
        )

    def test_over_short_one_cent_beyond_tolerance_flags(self, api):
        """PRD §3.7: "If the absolute value of `over_short_cents` is at or
        below the program's `over_short_tolerance_cents` — a discrepancy
        exactly equal to the tolerance passes — the event continues straight
        from `COUNTED` to `RECONCILED`. Outside the tolerance the event
        instead lands in `FLAGGED`, and the recount loop begins: a flagged
        event can be counted again, each recount overwriting
        `closing_counted_cents` and recomputing the discrepancy, until some
        count lands within tolerance."

        Design: Difficulty/boundary_precision_check/over_short_exactly_at_tolerance_reconciles
        """
        event = self._setup_counted_event(api)
        res = validate_success(
            api.close_count(
                event["id"],
                {"closing_counted_cents": 13001},
                make_treasurer_headers("treas-01"),
            ),
            200,
        )
        assert res["over_short_cents"] == 501
        assert res["status"] == "FLAGGED", (
            "one cent beyond the 500 tolerance leaves the event FLAGGED"
        )
