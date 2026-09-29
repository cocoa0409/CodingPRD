"""Queue A — exact-threshold behaviour of the side-work limbs and of the
monthly tipped-employee test."""
from test_helpers import (
    PREPARER,
    assert_shift_minute_split,
    close_shift,
    compute_period,
    list_pay_lines_of,
    read_pay_period,
    read_shift,
    setup_side_work_pair_world,
    setup_threshold_pair_world,
    validate_success,
)


def _pay_line_for(pay_period_id: str, employee_id: str) -> dict:
    rows = list_pay_lines_of(pay_period_id, employee_id=employee_id)
    assert len(rows) == 1, (
        f"expected exactly one pay line for employee {employee_id}, got {len(rows)}"
    )
    return rows[0]


# ---------------------------------------------------------------------------
# boundary_precision_check /
# side_work_at_exact_twenty_percent_and_thirty_minute_limits_yields_no_overage
# ---------------------------------------------------------------------------
def test_side_work_exactly_at_both_limits_produces_no_non_credit_minutes(api):
    """96 of 480 minutes and a 30-minute block are both exactly allowed.

    PRD §3.5: "The **percentage limb** implements the eighty-twenty rule: the
    shift's side-work allowance is twenty percent of `scheduled_minutes`, with any
    fraction of a minute discarded, and the percentage excess is
    `side_work_minutes` minus that allowance, or 0 if the subtraction would go
    negative."
    PRD §3.5: "The **continuous limb** implements the thirty-minute rule: the
    continuous excess is `max_continuous_side_work_minutes` minus 30 minutes, or 0
    if the subtraction would go negative."
    PRD §3.5: "`tip_credit_eligible_minutes` is then `scheduled_minutes` minus
    `non_tip_credit_minutes`, and it is the only quantity a tip credit may ever be
    claimed against."

    Design: Difficulty/boundary_precision_check/side_work_at_exact_twenty_percent_and_thirty_minute_limits_yields_no_overage
    """
    world = setup_side_work_pair_world()

    closed = validate_success(api.close_shift(world["shift_first"]["id"], PREPARER))

    assert closed["scheduled_minutes"] == 480
    assert closed["side_work_minutes"] == 96
    assert closed["max_continuous_side_work_minutes"] == 30
    assert closed["non_tip_credit_minutes"] == 0, (
        "96 is exactly twenty percent of 480 and 30 is exactly the continuous "
        "limit, so neither limb produces an excess"
    )
    assert closed["tip_credit_eligible_minutes"] == 480
    assert closed["time_status"] == "CLOSED"
    assert closed["declaration_status"] == "UNDECLARED"
    assert_shift_minute_split(closed)


def test_one_minute_past_both_limits_takes_the_greater_limb_and_not_their_sum(api):
    """97 and 31 each overshoot by one minute; the answer is 1, not 2.

    PRD §3.5: "The two limbs are emphatically **not** added together. Whichever
    limb binds harder wins: `non_tip_credit_minutes` is the greater of the
    percentage excess and the continuous excess."
    PRD §3.4: "`total_credited_minutes` is the sum of `scheduled_minutes` over the
    period's shifts whose `time_status` is `CLOSED`."

    Design: Difficulty/boundary_precision_check/side_work_at_exact_twenty_percent_and_thirty_minute_limits_yields_no_overage
    """
    world = setup_side_work_pair_world()

    close_shift(world["shift_first"]["id"])
    over = validate_success(api.close_shift(world["shift_second"]["id"], PREPARER))

    assert over["side_work_minutes"] == 97
    assert over["max_continuous_side_work_minutes"] == 31
    assert over["non_tip_credit_minutes"] == 1, (
        "the percentage excess is 1 and the continuous excess is 1, so the "
        "greater of the two is 1 and never their sum of 2"
    )
    assert over["tip_credit_eligible_minutes"] == 479
    assert over["time_status"] == "CLOSED"
    assert_shift_minute_split(over)

    period = read_pay_period(world["pay_period"]["id"])
    assert period["total_credited_minutes"] == 960


# ---------------------------------------------------------------------------
# boundary_precision_check /
# tipped_employee_monthly_threshold_at_exactly_three_thousand_cents
# ---------------------------------------------------------------------------
def test_employee_reaching_the_monthly_threshold_exactly_qualifies_for_the_credit(api):
    """3000 cents "reaches at least" the threshold, so the credit is available.

    PRD §3.8: "`tipped_employee_qualified` is true only if all three of the
    following hold: the unit's `tip_credit_enabled` is true; at least one `CLOSED`
    shift of the period has a `tip_credit_eligible_minutes` greater than 0, which
    is the evidence that a valid pre-shift notice was on file; and the employee's
    `monthly_tip_baseline_cents`, plus the sum over the period's `CLOSED` shifts of
    `declared_cash_tips_cents` plus `declared_charged_tips_cents`, reaches at least
    the monthly threshold of 3000 cents."
    PRD §3.8: "`tip_credit_cents` is then the smallest of those three figures —
    the per-hour ceiling, the tips actually available, and the residual — floored
    at 0 so it can never be negative."

    Design: Difficulty/boundary_precision_check/tipped_employee_monthly_threshold_at_exactly_three_thousand_cents
    """
    world = setup_threshold_pair_world()
    compute_period(world["pay_period"]["id"])

    line = _pay_line_for(world["pay_period"]["id"], world["employee_first"]["id"])

    assert line["tipped_employee_qualified"] is True
    assert line["tip_credit_eligible_minutes"] == 480
    assert line["non_tip_credit_minutes"] == 0
    assert line["straight_cash_cents"] == 1704
    assert line["minimum_wage_obligation_cents"] == 5800
    assert line["tips_available_cents"] == 3000
    assert line["tip_credit_cents"] == 3000, (
        "the tips available bind hardest: 3000 is below both the 4096 per-hour "
        "ceiling and the 4096 residual"
    )
    assert line["topup_cents"] == 1096
    assert line["total_gross_cents"] == 2800


def test_employee_one_cent_short_of_the_threshold_loses_the_credit_entirely(api):
    """2999 cents fails the test, so every eligible minute becomes non-credit time.

    PRD §3.8: "If `tipped_employee_qualified` comes out false, `tip_credit_cents`
    is 0 for the whole line."
    PRD §3.8: "`tip_credit_eligible_minutes` is the sum of the shifts' own
    `tip_credit_eligible_minutes`, except that it is forced to 0 when
    `tipped_employee_qualified` is false."
    PRD §3.8: "`straight_cash_cents` is built from two rate bands, each rounded
    half up on its own and then added: the unit's `cash_wage_cents` applied to
    `tip_credit_eligible_minutes` converted to hours by dividing by sixty, plus the
    unit's `applicable_min_wage_cents` applied to `non_tip_credit_minutes` likewise
    converted to hours."

    Design: Difficulty/boundary_precision_check/tipped_employee_monthly_threshold_at_exactly_three_thousand_cents
    """
    world = setup_threshold_pair_world()
    compute_period(world["pay_period"]["id"])

    line = _pay_line_for(world["pay_period"]["id"], world["employee_second"]["id"])

    assert line["tipped_employee_qualified"] is False
    assert line["tip_credit_eligible_minutes"] == 0
    assert line["non_tip_credit_minutes"] == 480
    assert line["straight_cash_cents"] == 5800, (
        "with no credit-eligible minutes the whole shift is paid at the "
        "applicable minimum wage of 725 cents an hour"
    )
    assert line["minimum_wage_obligation_cents"] == 5800
    assert line["tip_credit_cents"] == 0
    assert line["topup_cents"] == 0
    assert line["total_gross_cents"] == 5800

    # The shift itself keeps the eligible minutes the close classified; only the
    # line forces them to zero.
    shift = read_shift(world["shift_second"]["id"])
    assert shift["tip_credit_eligible_minutes"] == 480

    period = read_pay_period(world["pay_period"]["id"])
    assert period["total_tip_credit_cents"] == 3000
    assert period["total_topup_cents"] == 1096
