"""Table sessions: provisional/final charge calculation, peak split, discount,
peak-hour boundary, insufficient funds, bubble-up completion, and the check-in
table-active guard."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
)
from test_helpers import fixtures as fx


def _reserved_session(api, discount_pct=0.10, rate=1200, funded=100_000,
                      start="2026-07-02T17:00:00Z", end="2026-07-02T19:00:00Z"):
    """Build SILVER member + rate table + confirmed reservation, set clock to start,
    check in (opening a session). Returns (member, table, reservation, session)."""
    plan = fx.make_plan(tier="SILVER", monthly_fee_cents=5000, table_discount_pct=discount_pct)
    member = fx.make_funded_member(plan["id"], funded)
    table = fx.make_table(table_type="POOL_9FT", seat_capacity=6, hourly_rate_cents=rate)
    res = fx.make_confirmed_reservation(member["id"], table["id"], start, end)
    fx.set_clock(start)
    session = fx.checkin_reservation(res["id"])
    return member, table, res, session


class TestDualVariantCharge:
    def test_provisional_charge_off_peak_flat_no_discount(self, api):
        """PRD 3.3: "The provisional charge is the billed minutes multiplied by the
        table's hourly_rate_cents divided by sixty, rounded half up to a whole cent.
        Peak pricing and member discounts are deliberately ignored at this stage."

        120 reserved minutes * 1200/60 = 2400, no peak, no discount.

        Design: Difficulty/dual_variant_calc/session_charge_provisional_vs_final
        """
        _m, _t, _r, session = _reserved_session(api)
        assert session["provisional_charge_cents"] == 2400

    def test_final_charge_peak_split_plus_discount_and_wallet_debit(self, api):
        """PRD 3.3: "The gross charge is the off-peak minutes at the plain per-minute
        rate plus the peak minutes at the per-minute rate multiplied by 1.5." "The final
        charge is the gross multiplied by one minus the discount, rounded half up to a
        whole cent exactly once, after the discount is applied." "Closing a session
        debits final_charge_cents from the member's wallet_credit_cents"

        [17:00,19:00): 60 off-peak + 60 peak = 1200 + 1800 = 3000 gross;
        SILVER 0.10 discount -> 2700; wallet 100000 - 2700 = 97300.

        Design: Difficulty/dual_variant_calc/session_charge_provisional_vs_final
        """
        member, _t, _r, session = _reserved_session(api)
        fx.set_clock("2026-07-02T19:00:00Z")
        closed = validate_success(api.close_session(session["id"], TEST_USERS["frontdesk"]))
        assert closed["final_charge_cents"] == 2700
        assert closed["provisional_charge_cents"] != closed["final_charge_cents"]
        after = validate_success(api.get_member(member["id"], TEST_USERS["manager"]))
        assert after["wallet_credit_cents"] == 97300


class TestCombinatorialFinalCharge:
    def test_final_charge_combines_rate_peak_and_discount(self, api):
        """PRD 3.3: "The gross charge is the off-peak minutes at the plain per-minute
        rate plus the peak minutes at the per-minute rate multiplied by 1.5." "The final
        charge is the gross multiplied by one minus the discount, rounded half up to a
        whole cent exactly once, after the discount is applied."

        rate 1200, [17:00,19:00) SILVER window -> final 2700.

        Design: Difficulty/combinatorial_formula/session_final_peak_split_and_discount_mode_a
        """
        _m, _t, _r, session = _reserved_session(api)
        fx.set_clock("2026-07-02T19:00:00Z")
        closed = validate_success(api.close_session(session["id"], TEST_USERS["frontdesk"]))
        assert closed["final_charge_cents"] == 2700

    def test_final_charge_debited_from_member_wallet(self, api):
        """PRD 3.3: "Closing a session debits final_charge_cents from the member's
        wallet_credit_cents, but only when the session has a member_id"

        Design: Difficulty/combinatorial_formula/session_final_peak_split_and_discount_mode_a
        """
        member, _t, _r, session = _reserved_session(api)
        fx.set_clock("2026-07-02T19:00:00Z")
        validate_success(api.close_session(session["id"], TEST_USERS["frontdesk"]))
        after = validate_success(api.get_member(member["id"], TEST_USERS["manager"]))
        assert after["wallet_credit_cents"] == 97300


class TestPeakBoundary:
    def test_offpeak_window_ending_exactly_at_1800_has_no_peak(self, api):
        """PRD 3.3: "peak means the minute's hour-of-day (UTC) is at or after 18:00 and
        before 24:00 — that is, the six-hour evening block from 6 p.m. up to (but not
        including) midnight."

        A walk-in [17:30,18:00) has zero peak minutes: 30 * 1200/60 = 600.

        Design: Difficulty/boundary_precision_check/peak_boundary_offpeak_window_ends_exactly_1800
        """
        table = fx.make_table(table_type="POOL_9FT", seat_capacity=6, hourly_rate_cents=1200)
        fx.set_clock("2026-07-02T17:30:00Z")
        session = fx.open_walkin_session(table["id"])
        fx.set_clock("2026-07-02T18:00:00Z")
        closed = validate_success(api.close_session(session["id"], TEST_USERS["frontdesk"]))
        assert closed["final_charge_cents"] == 600

    def test_window_crossing_1800_counts_peak_minutes(self, api):
        """PRD 3.3: "peak means the minute's hour-of-day (UTC) is at or after 18:00 and
        before 24:00" "The gross charge is the off-peak minutes at the plain per-minute
        rate plus the peak minutes at the per-minute rate multiplied by 1.5."

        A walk-in [17:30,18:30): 30 off-peak + 30 peak = 600 + 900 = 1500.

        Design: Difficulty/boundary_precision_check/peak_boundary_offpeak_window_ends_exactly_1800
        """
        table = fx.make_table(table_type="POOL_9FT", seat_capacity=6, hourly_rate_cents=1200)
        fx.set_clock("2026-07-02T17:30:00Z")
        session = fx.open_walkin_session(table["id"])
        fx.set_clock("2026-07-02T18:30:00Z")
        closed = validate_success(api.close_session(session["id"], TEST_USERS["frontdesk"]))
        assert closed["final_charge_cents"] == 1500


class TestSessionCloseFunds:
    def test_close_insufficient_funds_leaves_session_open(self, api):
        """PRD 2.6: "any debit that would drive wallet_credit_cents below zero is
        rejected with ERR_INSUFFICIENT_FUNDS (HTTP 402) and the balance is left
        unchanged."
        PRD 3.3: "a debit that would take the wallet below zero is refused with
        ERR_INSUFFICIENT_FUNDS."

        Design: Corner/validations/session_close_insufficient_funds
        """
        plan = fx.make_plan(tier="BRONZE", monthly_fee_cents=3000, table_discount_pct=0.0)
        member = fx.make_funded_member(plan["id"], 100)
        table = fx.make_table(table_type="POOL_9FT", seat_capacity=6, hourly_rate_cents=1200)
        fx.set_clock("2026-07-02T17:30:00Z")
        session = fx.open_walkin_session(table["id"], member_id=member["id"])
        fx.set_clock("2026-07-02T18:00:00Z")
        resp = api.close_session(session["id"], TEST_USERS["frontdesk"])
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDS.value, expected_status=402)
        after = validate_success(api.get_session(session["id"], TEST_USERS["frontdesk"]))
        assert after["status"] == "OPEN"


class TestBubbleUp:
    def test_close_bubbles_reservation_to_completed(self, api):
        """PRD 3.3: "If the session realizes a reservation (its reservation_id is set),
        closing it bubbles the reservation CHECKED_IN -> COMPLETED."

        Design: Corner/state_machines/session_close_bubbles_reservation_to_completed
        """
        plan = fx.make_plan(tier="BRONZE", monthly_fee_cents=3000, table_discount_pct=0.0)
        member = fx.make_funded_member(plan["id"], 50000)
        table = fx.make_table(table_type="POOL_7FT", seat_capacity=4, hourly_rate_cents=1000)
        res = fx.make_confirmed_reservation(member["id"], table["id"],
                                            "2026-07-02T13:00:00Z", "2026-07-02T14:00:00Z")
        fx.set_clock("2026-07-02T13:00:00Z")
        session = fx.checkin_reservation(res["id"])
        fx.set_clock("2026-07-02T14:00:00Z")
        closed = validate_success(api.close_session(session["id"], TEST_USERS["frontdesk"]))
        assert closed["status"] == "CLOSED"
        after = validate_success(api.get_reservation(res["id"], TEST_USERS["frontdesk"]))
        assert after["status"] == "COMPLETED"


class TestCheckinTableActive:
    def test_checkin_blocked_when_table_in_maintenance(self, api):
        """PRD 2.8: "Table availability — a table required by a confirm, check-in,
        reschedule, walk-in session open, or event book must be ACTIVE (not MAINTENANCE
        or RETIRED), else ERR_TABLE_NOT_ACTIVE (409)."

        Design: Difficulty/cross_entity_state_dependency/checkin_requires_table_active
        """
        plan = fx.make_plan(tier="BRONZE", monthly_fee_cents=3000, table_discount_pct=0.0)
        member = fx.make_funded_member(plan["id"], 50000)
        table = fx.make_table(table_type="POOL_7FT", seat_capacity=4, hourly_rate_cents=1000)
        res = fx.make_confirmed_reservation(member["id"], table["id"],
                                            "2026-07-02T10:00:00Z", "2026-07-02T11:00:00Z")
        # Advance past start so maintenance does not cancel the (now non-future) reservation.
        fx.set_clock("2026-07-02T10:01:00Z")
        validate_success(api.table_maintenance(table["id"], TEST_USERS["manager"]))
        resp = api.checkin_reservation(res["id"], TEST_USERS["frontdesk"])
        validate_error(resp, ApiErrorId.ERR_TABLE_NOT_ACTIVE.value)

    def test_checkin_blocked_leaves_reservation_confirmed(self, api):
        """PRD 3.2: "A FrontDesk operator checks in a CONFIRMED reservation once the
        table is ACTIVE and the current logical time is at or after start_at minus
        fifteen minutes"

        A check-in refused because the table is in MAINTENANCE leaves the reservation
        in CONFIRMED (no transition occurs).

        Design: Difficulty/cross_entity_state_dependency/checkin_requires_table_active
        """
        plan = fx.make_plan(tier="BRONZE", monthly_fee_cents=3000, table_discount_pct=0.0)
        member = fx.make_funded_member(plan["id"], 50000)
        table = fx.make_table(table_type="POOL_7FT", seat_capacity=4, hourly_rate_cents=1000)
        res = fx.make_confirmed_reservation(member["id"], table["id"],
                                            "2026-07-02T10:00:00Z", "2026-07-02T11:00:00Z")
        fx.set_clock("2026-07-02T10:01:00Z")
        validate_success(api.table_maintenance(table["id"], TEST_USERS["manager"]))
        resp = api.checkin_reservation(res["id"], TEST_USERS["frontdesk"])
        validate_error(resp, ApiErrorId.ERR_TABLE_NOT_ACTIVE.value)
        after = validate_success(api.get_reservation(res["id"], TEST_USERS["frontdesk"]))
        assert after["status"] == "CONFIRMED"
