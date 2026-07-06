"""Pay-period provisional vs final totals (overtime reconciliation), pay-line
reversal, and pay-period terminal-state guarding.

Translates queue-A dual_variant_calc (payroll leg) and queue-B calculations /
state_machines pay instances.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    TEST_USERS,
    setup_open_pay_period,
    add_pay_line,
)

ADMIN = TEST_USERS["survey_admin_headers"]


# ── dual_variant_calc: payroll_provisional_vs_final_pay_period ────────────────

def test_pay_period_final_adds_overtime_premium_on_stipend_excess(api):
    """PRD §3.9: "carries two derived figures: `provisional_total_cents`, the
    running sum of `amount_cents` over the period's non-reversed pay lines, and
    `final_total_cents`, the reconciled total computed at lock."
    PRD §3.9: "if that stipend sum exceeds the period's `overtime_threshold_cents`,
    the excess above the threshold is multiplied by an overtime premium rate of one
    half and rounded half up to whole cents to yield that enumerator's premium."

    STIPEND 2300 + BONUS 500 -> provisional 2800. Stipend excess over the 2000
    threshold is 300; premium = round_half_up(0.5*300) = 150; final = 2950.

    Design: Difficulty/dual_variant_calc/payroll_provisional_vs_final_pay_period
    """
    ctx = setup_open_pay_period(overtime_threshold_cents=2000)
    pp_id = ctx["pay_period"]["id"]
    en_id = ctx["enumerator"]["id"]
    add_pay_line(pp_id, en_id, "STIPEND", 2300)
    add_pay_line(pp_id, en_id, "BONUS", 500)

    locked = validate_success(api.lock_pay_period(pp_id, ADMIN), 200)
    assert locked["status"] == "LOCKED"
    assert locked["provisional_total_cents"] == 2800
    assert locked["final_total_cents"] == 2950


def test_pay_period_bonus_does_not_feed_overtime(api):
    """PRD §3.9: "For each enumerator with at least one accrued line in the period,
    sum that enumerator's accrued `STIPEND` line amounts (only stipend lines feed
    overtime; `MILEAGE` and `BONUS` lines do not); if that stipend sum exceeds the
    period's `overtime_threshold_cents`, the excess above the threshold is
    multiplied by an overtime premium rate of one half and rounded half up to whole
    cents to yield that enumerator's premium."

    STIPEND 1000 + BONUS 5000 -> provisional 6000. The stipend sum (1000) does not
    exceed the 2000 threshold, so no premium accrues despite the large bonus:
    final == provisional == 6000.

    Design: Difficulty/dual_variant_calc/payroll_provisional_vs_final_pay_period
    """
    ctx = setup_open_pay_period(overtime_threshold_cents=2000)
    pp_id = ctx["pay_period"]["id"]
    en_id = ctx["enumerator"]["id"]
    add_pay_line(pp_id, en_id, "STIPEND", 1000)
    add_pay_line(pp_id, en_id, "BONUS", 5000)

    locked = validate_success(api.lock_pay_period(pp_id, ADMIN), 200)
    assert locked["provisional_total_cents"] == 6000
    assert locked["final_total_cents"] == 6000


# ── queue-B: pay-line reversal and terminal-state guarding ────────────────────

def test_reverse_pay_line_updates_totals(api):
    """PRD §3.9: "moves the line to `REVERSED`, subtracts its `amount_cents` from
    the period's `provisional_total_cents`, adds its `amount_cents` to the
    enumerator's `reversed_pay_cents`, and recomputes `net_pay_cents`. The
    enumerator's `gross_pay_cents` is deliberately left untouched by a reversal."

    Design: Corner/calculations/reverse_pay_line_updates_totals
    """
    ctx = setup_open_pay_period()
    pp_id = ctx["pay_period"]["id"]
    en_id = ctx["enumerator"]["id"]
    line = add_pay_line(pp_id, en_id, "STIPEND", 2300)

    reversed_line = validate_success(api.reverse_pay_line(line["id"], ADMIN), 200)
    assert reversed_line["status"] == "REVERSED"

    period = validate_success(api.get_pay_period(pp_id, ADMIN), 200)
    assert period["provisional_total_cents"] == 0
    en = validate_success(api.get_enumerator(en_id, ADMIN), 200)
    assert en["reversed_pay_cents"] == 2300
    assert en["net_pay_cents"] == 0


def test_lock_paid_pay_period_returns_invalid_state(api):
    """PRD §3.9: "Finally the administrator marks a locked period paid, moving it
    from `LOCKED` to `PAID` (a pay from any other state fails with
    `ERR_PAY_PERIOD_INVALID_STATE`); `PAID` is terminal."
    PRD §3.9: "A `SurveyAdmin` locks an `OPEN` period, moving it to `LOCKED` (a lock
    from any other state fails with `ERR_PAY_PERIOD_INVALID_STATE`)".

    Design: Corner/state_machines/lock_paid_pay_period_returns_invalid_state
    """
    ctx = setup_open_pay_period()
    pp_id = ctx["pay_period"]["id"]
    validate_success(api.lock_pay_period(pp_id, ADMIN), 200)
    validate_success(api.pay_pay_period(pp_id, ADMIN), 200)

    res = api.lock_pay_period(pp_id, ADMIN)
    validate_error(res, "ERR_PAY_PERIOD_INVALID_STATE", expected_status=409)
