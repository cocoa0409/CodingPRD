"""No-show / late-cancel fee proration, the strike multiplier, and the waive compensation.

Covers difficulty queue A instances on no-show fee proration (mode-b multiply-then-round),
the free-cancel boundary, and the no-show/waive compensating invariant.
"""
from test_helpers import (
    validate_success,
    bookable_scenario,
    book_appointment,
    set_clock,
    raise_client_strikes_to,
    create_table,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
FRONT = TEST_USERS["front_desk_headers"]


def test_true_no_show_full_fee_swedish_60(api):
    """PRD §3.7: "When lead time is 0 or negative, the fraction is 1.00 — the full session
    value." PRD §3.6: "It then sets settlement_status to PRICED with service_charge_cents of 0
    and client_owed_cents equal to the computed no_show_fee_cents."

    A Swedish-60 (base 12000) no-show by a first-strike client charges the full 12000.

    Design: Difficulty/dual_variant_calc/no_show_fee_proration_vs_membership_rollover
    """
    set_clock("2026-03-01T00:00:00Z")
    scn = bookable_scenario()
    appt = book_appointment(scn, start_at="2026-03-01T10:00:00Z", duration_minutes=60, payer="CASH")
    set_clock("2026-03-01T10:30:00Z")
    result = validate_success(api.no_show_appointment(appt["id"], FRONT))
    assert result["no_show_fee_cents"] == 12000, \
        f"true no-show on Swedish-60 should charge 12000, got {result['no_show_fee_cents']}"
    assert result["scheduling_status"] == "NO_SHOW"


def test_package_rollover_under_cap_after_renewal(api):
    """PRD §3.10: "First the kept amount is the smaller of the current credit_balance_sessions
    and the plan's rollover_cap_sessions ... Then the plan's included_sessions are granted with
    a CreditLedgerEntry of reason GRANT, so the new credit_balance_sessions equals the kept
    amount plus included_sessions."

    A package with included 2 / cap 1, never spent (balance 2), renewed past cycle end keeps
    min(2,1)=1 then grants 2 -> balance 3 — a session-count, not money.

    Design: Difficulty/dual_variant_calc/no_show_fee_proration_vs_membership_rollover
    """
    from test_helpers import create_plan, create_package
    set_clock("2026-03-01T00:00:00Z")
    client = validate_success(api.create_client(
        {"full_name": "Roll Client", "email": "rollc@example.com"}, FRONT), expected_status=201)
    plan = create_plan(name="RollPlanA", monthly_fee_cents=9000, included_sessions=2,
                       member_discount_pct=0.20, rollover_cap_sessions=1)
    pkg = create_package(client["id"], plan["id"], cycle_anchor_day=1)
    assert pkg["credit_balance_sessions"] == 2
    set_clock("2026-04-02T00:00:00Z")
    renewed = validate_success(api.renew_package(pkg["id"], ADMIN))
    assert renewed["credit_balance_sessions"] == 3, \
        f"kept min(2,1)=1 + granted 2 should be 3, got {renewed['credit_balance_sessions']}"
    ledger = validate_success(api.get_package_ledger(pkg["id"], ADMIN))
    assert ledger[-1]["balance_after"] == 3


def test_no_show_fee_multiply_then_round_with_strike_multiplier(api):
    """PRD §3.7: "The raw fee is the base session value multiplied by the fee fraction and then
    by the strike multiplier, all in exact rational arithmetic; no_show_fee_cents is that
    product rounded half up to whole cents exactly once, after the full multiply chain." PRD
    §3.7: "When the client's no_show_strikes is at least 3, the multiplier is 1.50."

    A Swedish-30 (base_session 6000) true no-show by a 4th-strike client: 6000 * 1.00 * 1.50 =
    9000.

    Design: Difficulty/combinatorial_formula/no_show_fee_multiply_then_round_mode_b
    """
    set_clock("2026-03-01T00:00:00Z")
    scn = bookable_scenario()
    # Drive the client to 3 strikes (three prior no-shows on 30-min slots).
    raise_client_strikes_to(scn, 3, base_start="2026-03-01T08:00:00Z")
    # The test appointment — its no-show makes the 4th strike, multiplier 1.5.
    tbl = create_table()
    appt = book_appointment(scn, table=tbl, start_at="2026-03-01T12:00:00Z", duration_minutes=30, payer="CASH")
    set_clock("2026-03-01T12:30:00Z")
    result = validate_success(api.no_show_appointment(appt["id"], FRONT))
    assert result["no_show_fee_cents"] == 9000, \
        f"base 6000 * 1.0 * 1.5 should round to 9000, got {result['no_show_fee_cents']}"
    client = validate_success(api.get_client(scn["client"]["id"], ADMIN))
    assert client["no_show_strikes"] == 4


def test_no_show_increments_strike_count(api):
    """PRD §3.6: "Marking a no-show sets scheduling_status to NO_SHOW, increments the client's
    no_show_strikes by 1, and — using the strike count as just incremented — computes
    no_show_fee_cents through the no-show proration of §3.7."

    Design: Difficulty/combinatorial_formula/no_show_fee_multiply_then_round_mode_b
    """
    set_clock("2026-03-01T00:00:00Z")
    scn = bookable_scenario()
    appt = book_appointment(scn, start_at="2026-03-01T10:00:00Z", duration_minutes=30, payer="CASH")
    set_clock("2026-03-01T10:30:00Z")
    validate_success(api.no_show_appointment(appt["id"], FRONT))
    client = validate_success(api.get_client(scn["client"]["id"], ADMIN))
    assert client["no_show_strikes"] == 1, \
        f"first no-show should set strikes to 1, got {client['no_show_strikes']}"


def test_free_cancel_window_exact_1440_no_fee(api):
    """PRD §3.7: "When lead time is at least 1440 minutes (that is, 24 hours or more before the
    start), the fraction is 0 — no fee." PRD §3.7: "a lead time of exactly 1440 minutes takes
    the 0 band."

    Cancelling a Swedish-60 exactly 1440 minutes before start_at carries no_show_fee_cents 0.

    Design: Difficulty/boundary_precision_check/free_cancel_window_exact_1440_no_fee
    """
    set_clock("2026-03-02T08:00:00Z")
    scn = bookable_scenario()
    appt = book_appointment(scn, start_at="2026-03-03T10:00:00Z", duration_minutes=60, payer="CASH")
    set_clock("2026-03-02T10:00:00Z")  # exactly 1440 minutes before start
    result = validate_success(api.cancel_appointment(appt["id"], {"cancel_reason": "LATE_CANCEL"}, FRONT))
    assert result["no_show_fee_cents"] == 0, \
        f"cancel at exactly 1440 min lead should carry 0 fee, got {result['no_show_fee_cents']}"
    assert result["scheduling_status"] == "CANCELLED"


def test_late_cancel_one_minute_inside_window_charges_fee(api):
    """PRD §3.7: "When lead time is at least 120 minutes but less than 1440, the fraction is
    0.50." PRD §3.6: "a cancellation made when the clock has already passed the
    free-cancellation cutoff relative to start_at is treated as a late cancel and is priced
    through the late-cancel proration ... setting settlement_status to PRICED with the computed
    no_show_fee_cents."

    One minute inside the free window (1439 min lead) on a Swedish-60 (base 12000) charges
    12000 * 0.50 = 6000.

    Design: Difficulty/boundary_precision_check/free_cancel_window_exact_1440_no_fee
    """
    set_clock("2026-03-02T08:00:00Z")
    scn = bookable_scenario()
    appt = book_appointment(scn, start_at="2026-03-03T10:00:00Z", duration_minutes=60, payer="CASH")
    set_clock("2026-03-02T10:01:00Z")  # 1439 minutes before start
    result = validate_success(api.cancel_appointment(appt["id"], {"cancel_reason": "LATE_CANCEL"}, FRONT))
    assert result["no_show_fee_cents"] == 6000, \
        f"late cancel at 1439 min lead should charge 6000, got {result['no_show_fee_cents']}"
    assert result["settlement_status"] == "PRICED"


def test_no_show_then_waive_conserves_strikes(api):
    """PRD §3.6: "Waiving is the system's compensating revert: it re-opens the session by
    setting scheduling_status back to SCHEDULED, decrements the client's no_show_strikes by 1
    (never below 0), and undoes the priced fee by setting settlement_status back to UNSETTLED
    with no_show_fee_cents and client_owed_cents both reset to 0."

    no-show (strikes 0->1, fee 12000) followed by waive nets strikes back to 0 and fee to 0.

    Design: Difficulty/compensating_invariant/no_show_then_waive_conserves_strikes
    """
    set_clock("2026-03-02T07:00:00Z")
    scn = bookable_scenario()
    appt = book_appointment(scn, start_at="2026-03-02T09:00:00Z", duration_minutes=60, payer="CASH")
    set_clock("2026-03-02T09:30:00Z")
    validate_success(api.no_show_appointment(appt["id"], FRONT))
    waived = validate_success(api.waive_no_show(appt["id"], ADMIN))
    assert waived["scheduling_status"] == "SCHEDULED"
    assert waived["settlement_status"] == "UNSETTLED"
    assert waived["no_show_fee_cents"] == 0
    client = validate_success(api.get_client(scn["client"]["id"], ADMIN))
    assert client["no_show_strikes"] == 0, \
        f"strikes must net to 0 after no-show+waive, got {client['no_show_strikes']}"


def test_waive_decrements_strike_floored_at_zero(api):
    """PRD §3.6: "the invariant the practice cares about is that strikes minus waives nets to
    zero across a no-show followed by its waiver, so the strike the no-show added is exactly the
    strike the waiver removes." PRD §3.6: "decrements the client's no_show_strikes by 1 (never
    below 0)."

    Design: Difficulty/compensating_invariant/no_show_then_waive_conserves_strikes
    """
    set_clock("2026-03-02T07:00:00Z")
    scn = bookable_scenario()
    appt = book_appointment(scn, start_at="2026-03-02T09:00:00Z", duration_minutes=60, payer="CASH")
    set_clock("2026-03-02T09:30:00Z")
    after_ns = validate_success(api.no_show_appointment(appt["id"], FRONT))
    assert after_ns["no_show_fee_cents"] == 12000
    client_after_ns = validate_success(api.get_client(scn["client"]["id"], ADMIN))
    assert client_after_ns["no_show_strikes"] == 1
    validate_success(api.waive_no_show(appt["id"], ADMIN))
    client_after_waive = validate_success(api.get_client(scn["client"]["id"], ADMIN))
    assert client_after_waive["no_show_strikes"] == 0
