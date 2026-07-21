"""Transitive cascades: the table-retire -> reservation -> event -> deposit-refund
chain, and the no-show -> suspension -> booking-cancellation chain."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_reservation_payload,
)
from test_helpers import fixtures as fx


class TestTableRetireCascade:
    def _setup_booked_on_single_table(self, api):
        """Booked, deposit-paid event on a single table (one CONFIRMED event
        reservation). Returns (host, event, table, reservation)."""
        host, ev, tables = fx.setup_booked_event(
            table_count=1, start_at="2026-07-03T10:00:00Z", end_at="2026-07-03T12:00:00Z",
        )
        listing = api.list_reservations(TEST_USERS["frontdesk"], params={"event_id": ev["id"]})
        data = validate_success(listing)
        return host, ev, tables[0], data[0]

    def test_retire_cancels_table_and_event_reservation(self, api):
        """PRD 3.2: "Both maintenance and retirement carry the same cascade: every future
        reservation on that table still in PENDING or CONFIRMED (whose start_at is at or
        after the current logical time) is moved to CANCELLED."

        Design: Difficulty/transitive_cascade/table_retire_cancels_reservation_cancels_event_refunds_deposit
        """
        _host, _ev, table, reservation = self._setup_booked_on_single_table(api)
        retired = validate_success(api.table_retire(table["id"], TEST_USERS["manager"]))
        assert retired["status"] == "RETIRED"
        after_res = validate_success(api.get_reservation(reservation["id"], TEST_USERS["frontdesk"]))
        assert after_res["status"] == "CANCELLED"

    def test_retire_cascades_to_event_cancel_and_deposit_refund(self, api):
        """PRD 3.2: "If a cancelled reservation was created by an event booking (its
        event_id is set) and that event is still in booking status BOOKED or CONFIRMED,
        cancelling the reservation cancels that event too"
        PRD 3.7: "if the event's payment_status was DEPOSIT_PAID, the collected
        deposit_paid_cents is credited back to the host's wallet and payment_status
        becomes REFUNDED."

        Host wallet returns to 100000 (deposit 2000 refunded).

        Design: Difficulty/transitive_cascade/table_retire_cancels_reservation_cancels_event_refunds_deposit
        """
        host, ev, table, _reservation = self._setup_booked_on_single_table(api)
        validate_success(api.table_retire(table["id"], TEST_USERS["manager"]))
        after_ev = validate_success(api.get_event(ev["id"], TEST_USERS["manager"]))
        assert after_ev["booking_status"] == "CANCELLED"
        assert after_ev["payment_status"] == "REFUNDED"
        after_host = validate_success(api.get_member(host["id"], TEST_USERS["manager"]))
        assert after_host["wallet_credit_cents"] == 100000


def _suspend_via_three_noshows(api, with_survivor=False):
    """Confirm three 2026-07-02 reservations, no-show each (advancing the clock),
    driving the member to SUSPENDED on the third strike. Optionally also create a
    2026-07-05 survivor reservation (CONFIRMED before suspension). Returns
    (member, table, reservations) where reservations = [r1, r2, r3, (survivor)]."""
    plan = fx.make_plan(tier="BRONZE", monthly_fee_cents=3000, table_discount_pct=0.0)
    member = fx.make_member(plan["id"])
    table = fx.make_table(table_type="POOL_7FT", seat_capacity=4, hourly_rate_cents=1000)
    windows = [("2026-07-02T10:00:00Z", "2026-07-02T11:00:00Z"),
               ("2026-07-02T12:00:00Z", "2026-07-02T13:00:00Z"),
               ("2026-07-02T14:00:00Z", "2026-07-02T15:00:00Z")]
    reservations = [fx.make_confirmed_reservation(member["id"], table["id"], s, e) for s, e in windows]
    if with_survivor:
        reservations.append(
            fx.make_confirmed_reservation(member["id"], table["id"],
                                          "2026-07-05T10:00:00Z", "2026-07-05T11:00:00Z")
        )
    for res, clk in zip(reservations[:3], ["2026-07-02T10:20:00Z", "2026-07-02T12:20:00Z",
                                           "2026-07-02T14:20:00Z"]):
        fx.set_clock(clk)
        validate_success(api.noshow_reservation(res["id"], TEST_USERS["frontdesk"]))
    return member, table, reservations


class TestNoShowSuspensionCascade:
    def test_third_noshow_suspends_member(self, api):
        """PRD 3.1: "Each no-show adds one to the member's no_show_strikes. When
        no_show_strikes reaches three, the member transitions ACTIVE -> SUSPENDED, and
        that suspension in turn cancels every one of the member's reservations still in
        PENDING or CONFIRMED."

        Design: Difficulty/transitive_cascade/reservation_noshow_suspends_member_cancels_other_reservations
        """
        member, _table, _res = _suspend_via_three_noshows(api, with_survivor=True)
        after = validate_success(api.get_member(member["id"], TEST_USERS["manager"]))
        assert after["no_show_strikes"] == 3
        assert after["membership_status"] == "SUSPENDED"

    def test_suspension_cancels_surviving_confirmed_reservation(self, api):
        """PRD 3.1: "When no_show_strikes reaches three, the member transitions ACTIVE ->
        SUSPENDED, and that suspension in turn cancels every one of the member's
        reservations still in PENDING or CONFIRMED."
        PRD 3.2: "a FrontDesk operator may mark the reservation a no-show once the current
        logical time is at or after start_at plus fifteen minutes; this moves it CONFIRMED
        -> NO_SHOW"

        Design: Difficulty/transitive_cascade/reservation_noshow_suspends_member_cancels_other_reservations
        """
        _member, _table, reservations = _suspend_via_three_noshows(api, with_survivor=True)
        third = validate_success(api.get_reservation(reservations[2]["id"], TEST_USERS["frontdesk"]))
        survivor = validate_success(api.get_reservation(reservations[3]["id"], TEST_USERS["frontdesk"]))
        assert third["status"] == "NO_SHOW"
        assert survivor["status"] == "CANCELLED"


class TestSuspendedMemberGuard:
    def test_suspended_member_cannot_book(self, api):
        """PRD 3.1: "A SUSPENDED member is barred from creating new reservations,
        tournament entries, or events (ERR_MEMBER_SUSPENDED)".

        Design: Corner/validations/suspended_member_cannot_create_reservation
        """
        member, table, _res = _suspend_via_three_noshows(api, with_survivor=False)
        resp = api.create_reservation(
            create_reservation_payload(member_id=member["id"], table_id=table["id"],
                                       start_at="2026-07-11T10:00:00Z",
                                       end_at="2026-07-11T11:00:00Z", party_size=2),
            TEST_USERS["frontdesk"],
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_SUSPENDED.value)
        after = validate_success(api.get_member(member["id"], TEST_USERS["manager"]))
        assert after["membership_status"] == "SUSPENDED"
