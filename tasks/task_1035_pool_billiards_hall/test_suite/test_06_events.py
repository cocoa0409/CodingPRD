"""Private events: quote tier pricing, the two independent booking/payment axes,
and aggregate table-capacity checking at quote time."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx


class TestEventQuote:
    def test_three_table_four_hour_bulk_tier(self, api):
        """PRD 3.7: "The base is table_count times that hour count times the event rate
        of 4000 cents per table-hour. A bulk discount then applies by table count, with
        inclusive thresholds: 15 percent off when table_count is at least 10, otherwise
        10 percent off when it is at least 6, otherwise 5 percent off when it is at least
        3, otherwise none. The quote_cents is the base times one minus the bulk fraction,
        rounded half up to a whole cent. The deposit_cents is 25 percent of quote_cents,
        rounded half up to a whole cent."

        3 tables * 4 hours * 4000 = 48000; >=3 tier (0.05) -> 45600; deposit 11400.

        Design: Corner/calculations/event_quote_three_table_bulk_tier_boundary
        """
        _host, ev, _tables = fx.setup_quoted_event(
            table_count=3, start_at="2026-07-10T10:00:00Z", end_at="2026-07-10T14:00:00Z",
        )
        assert ev["quote_cents"] == 45600
        assert ev["deposit_cents"] == 11400


class TestEventParallelAxes:
    def test_booking_advances_while_payment_holds_at_deposit_paid(self, api):
        """PRD 3.7: "The host books a QUOTED event (booking_status QUOTED -> BOOKED)"
        "The host member pays the deposit (payment_status UNPAID -> DEPOSIT_PAID) while
        the event is QUOTED or BOOKED" "The two axes move independently except where a
        transition on one explicitly guards on the other."

        After pay-deposit then book: booking_status BOOKED, payment_status DEPOSIT_PAID.

        Design: Difficulty/non_linear_state_machine/event_parallel_booking_and_payment_axes
        """
        _host, ev, _tables = fx.setup_booked_event(
            table_count=1, start_at="2026-07-04T10:00:00Z", end_at="2026-07-04T12:00:00Z",
        )
        assert ev["booking_status"] == "BOOKED"
        assert ev["payment_status"] == "DEPOSIT_PAID"

    def test_deposit_recorded_and_host_wallet_debited(self, api):
        """PRD 3.7: "payment debits deposit_cents from the host wallet and records it in
        deposit_paid_cents."

        1 table * 2 hours * 4000 = 8000 quote; deposit 2000; host wallet 100000 - 2000
        = 98000; deposit_paid_cents 2000.

        Design: Difficulty/non_linear_state_machine/event_parallel_booking_and_payment_axes
        """
        host, ev, _tables = fx.setup_booked_event(
            table_count=1, start_at="2026-07-04T10:00:00Z", end_at="2026-07-04T12:00:00Z",
        )
        assert ev["deposit_paid_cents"] == 2000
        after = validate_success(api.get_member(host["id"], TEST_USERS["manager"]))
        assert after["wallet_credit_cents"] == 98000


class TestEventCapacity:
    def _setup_one_free_table(self, api):
        plan = fx.make_plan(tier="GOLD", monthly_fee_cents=8000, table_discount_pct=0.20)
        host = fx.make_member(plan["id"])
        t1 = fx.make_table(table_type="POOL_9FT", seat_capacity=8, hourly_rate_cents=1200)
        fx.make_table(table_type="POOL_9FT", seat_capacity=8, hourly_rate_cents=1200)
        fx.make_confirmed_reservation(host["id"], t1["id"],
                                      "2026-07-08T10:00:00Z", "2026-07-08T12:00:00Z")
        ev = fx.make_event(host["id"], 2, "2026-07-08T10:00:00Z", "2026-07-08T12:00:00Z")
        return host, ev

    def test_quote_rejected_when_insufficient_free_tables(self, api):
        """PRD 3.7: "A Manager quotes an INQUIRY event (INQUIRY -> QUOTED), which
        requires that the window has enough capacity — at least table_count ACTIVE tables
        with no CONFIRMED or CHECKED_IN reservation overlapping [start_at, end_at) across
        the whole table pool; otherwise the quote is refused with
        ERR_EVENT_CAPACITY_UNAVAILABLE."

        Design: Difficulty/resource_temporal_overlap/event_aggregate_capacity_only_one_free_table
        """
        _host, ev = self._setup_one_free_table(api)
        resp = api.quote_event(ev["id"], TEST_USERS["manager"])
        validate_error(resp, ApiErrorId.ERR_EVENT_CAPACITY_UNAVAILABLE.value)

    def test_quote_rejection_leaves_event_in_inquiry(self, api):
        """PRD 3.7: "A Manager quotes an INQUIRY event (INQUIRY -> QUOTED), which
        requires that the window has enough capacity — at least table_count ACTIVE tables
        with no CONFIRMED or CHECKED_IN reservation overlapping [start_at, end_at) across
        the whole table pool; otherwise the quote is refused with
        ERR_EVENT_CAPACITY_UNAVAILABLE."

        Design: Difficulty/resource_temporal_overlap/event_aggregate_capacity_only_one_free_table
        """
        _host, ev = self._setup_one_free_table(api)
        validate_error(api.quote_event(ev["id"], TEST_USERS["manager"]),
                       ApiErrorId.ERR_EVENT_CAPACITY_UNAVAILABLE.value)
        after = validate_success(api.get_event(ev["id"], TEST_USERS["manager"]))
        assert after["booking_status"] == "INQUIRY"
