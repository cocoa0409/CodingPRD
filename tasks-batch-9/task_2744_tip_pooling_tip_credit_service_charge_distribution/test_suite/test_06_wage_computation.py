"""Queue A — the wage computation itself: the two variants that price the same
week differently, and the pinned nine-step order that a service charge exposes."""
from test_helpers import (
    approve_period,
    compute_period,
    list_pay_lines_of,
    read_pay_period,
    read_service_charge,
    read_shift,
    setup_new_york_overtime_world,
    setup_texas_two_shift_world,
    sole_pay_line_of,
)


# ---------------------------------------------------------------------------
# dual_variant_calc / pay_line_tip_credit_weekly_aggregate_versus_per_shift
# ---------------------------------------------------------------------------
def test_weekly_aggregate_compute_lets_the_heavy_night_subsidise_the_light_one(api):
    """One obligation over 960 minutes claims all 5500 cents of the week's tips.

    PRD §3.8: "Under `WEEKLY_AGGREGATE`, which is the variant a compute produces,
    steps 6 through 8 run **once** across the employee's whole workweek: a single
    obligation, a single three-way cap and a single top-up, all derived from the
    summed minutes and the summed tips."
    PRD §3.8: "`minimum_wage_obligation_cents` is again two bands, each rounded
    half up and then summed: the unit's `applicable_min_wage_cents` applied to
    `regular_minutes` divided by sixty, plus one and one half times that same
    `applicable_min_wage_cents` applied to `overtime_minutes` divided by sixty."
    PRD §3.8: "`topup_cents` is `minimum_wage_obligation_cents` less
    `straight_cash_cents`, less `service_charge_wages_cents`, less
    `overtime_premium_cents`, less `tip_credit_cents`, floored at 0."

    Design: Difficulty/dual_variant_calc/pay_line_tip_credit_weekly_aggregate_versus_per_shift
    """
    world = setup_texas_two_shift_world()

    compute_period(world["pay_period"]["id"])
    line = sole_pay_line_of(world["pay_period"]["id"])

    assert line["variant"] == "WEEKLY_AGGREGATE"
    assert line["status"] == "DRAFT"
    assert line["total_minutes"] == 960
    assert line["tip_credit_eligible_minutes"] == 960
    assert line["straight_cash_cents"] == 3408, "213 cents an hour across sixteen hours"
    assert line["minimum_wage_obligation_cents"] == 11600
    assert line["tips_available_cents"] == 5500
    assert line["tip_credit_cents"] == 5500, (
        "the tips available bind: 5500 is below both the 8192 per-hour ceiling and "
        "the 8192 residual"
    )
    assert line["topup_cents"] == 2692
    assert line["total_gross_cents"] == 6100

    period = read_pay_period(world["pay_period"]["id"])
    assert period["compute_variant"] == "WEEKLY_AGGREGATE"
    assert period["total_tip_credit_cents"] == 5500
    assert period["total_topup_cents"] == 2692


def test_approval_reprices_the_same_week_shift_by_shift_and_costs_the_employer_more(api):
    """Splitting the week strands 904 cents of tips and raises the top-up to 3596.

    PRD §3.8: "Under `PER_SHIFT`, which is the variant an approval produces, steps
    6 through 8 run **separately for each `CLOSED` shift**, each using only that
    shift's minutes and only that shift's own tips, and the per-shift results are
    summed into the line."
    PRD §3.8: "The per-shift credit is additionally written back onto each shift as
    `shift_tip_credit_cents`, which stays 0 until the owning period is approved."
    PRD §3.8: "Approval drives it `DRAFT → FINAL`: its `variant` is switched from
    `WEEKLY_AGGREGATE` to `PER_SHIFT`, its wage figures are recomputed under that
    variant, its `allocated_tips_cents` is written by the reporting test, and its
    `version` is incremented by 1."

    Design: Difficulty/dual_variant_calc/pay_line_tip_credit_weekly_aggregate_versus_per_shift
    """
    world = setup_texas_two_shift_world(compute=True)
    assert read_shift(world["shift_a"]["id"])["shift_tip_credit_cents"] == 0

    approve_period(world["pay_period"]["id"])
    line = sole_pay_line_of(world["pay_period"]["id"])

    assert line["variant"] == "PER_SHIFT"
    assert line["status"] == "FINAL"
    assert line["straight_cash_cents"] == 3408, (
        "steps 0 through 5 are identical in both variants"
    )
    assert line["tip_credit_cents"] == 4596, (
        "4096 capped on the 5000-cent night plus only 500 on the light night"
    )
    assert line["topup_cents"] == 3596
    assert line["total_gross_cents"] == 7004

    assert read_shift(world["shift_a"]["id"])["shift_tip_credit_cents"] == 4096
    assert read_shift(world["shift_b"]["id"])["shift_tip_credit_cents"] == 500

    period = read_pay_period(world["pay_period"]["id"])
    assert period["compute_variant"] == "PER_SHIFT"
    assert period["total_tip_credit_cents"] == 4596
    assert period["total_topup_cents"] == 3596


# ---------------------------------------------------------------------------
# combinatorial_formula / pay_line_regular_rate_excludes_topup_pinned_order
# ---------------------------------------------------------------------------
def _sole_line(pay_period_id: str) -> dict:
    rows = list_pay_lines_of(pay_period_id)
    assert len(rows) == 1, f"one employee worked this week, got {len(rows)} lines"
    return rows[0]


def test_wages_treated_service_charge_lifts_the_regular_rate_and_the_premium(api):
    """The 6000-cent charge is inside the rate, giving 1133 an hour and 2833 of premium.

    PRD §3.8: "`regular_rate_cents_per_hour` is `straight_cash_cents` plus
    `service_charge_wages_cents`, divided by the number of hours worked — that is,
    by `total_minutes` divided by sixty — rounded half up."
    PRD §3.8: "`overtime_premium_cents` is one half of
    `regular_rate_cents_per_hour`, multiplied by `overtime_minutes` divided by
    sixty, rounded half up."
    PRD §3.8: "`overtime_minutes` is `total_minutes` less the 2,400-minute overtime
    threshold, or 0 if that subtraction would go negative. `regular_minutes` is
    `total_minutes` less `overtime_minutes`."

    Design: Difficulty/combinatorial_formula/pay_line_regular_rate_excludes_topup_pinned_order
    """
    world = setup_new_york_overtime_world()

    compute_period(world["pay_period"]["id"])
    line = _sole_line(world["pay_period"]["id"])

    assert line["total_minutes"] == 2700
    assert line["regular_minutes"] == 2400
    assert line["overtime_minutes"] == 300
    assert line["straight_cash_cents"] == 45000
    assert line["service_charge_wages_cents"] == 6000
    assert line["regular_rate_cents_per_hour"] == 1133, (
        "51000 cents over forty-five hours is 1133.33 an hour, rounded half up"
    )
    assert line["overtime_premium_cents"] == 2833, (
        "half of 1133 across five overtime hours is 2832.5, rounded half up"
    )
    assert line["minimum_wage_obligation_cents"] == 71250

    charge = read_service_charge(world["service_charge"]["id"])
    assert charge["status"] == "ALLOCATED"
    assert charge["treatment"] == "WAGES"
    assert charge["allocated_pay_period_id"] == world["pay_period"]["id"]
    assert charge["allocated_pool_id"] is None


def test_regular_rate_excludes_the_topup_so_the_residual_binds_the_credit(api):
    """The credit lands on 17417 — the residual — and the top-up therefore vanishes.

    PRD §3.8: "Tips, `TIPS`-treated service charges, the tip credit and the top-up
    are all excluded from this rate; the top-up is excluded deliberately, because
    including a figure that is itself derived from the rate would make the formula
    self-referential."
    PRD §3.8: "The residual is `minimum_wage_obligation_cents` less
    `straight_cash_cents`, less `service_charge_wages_cents`, less
    `overtime_premium_cents`."
    PRD §3.8: "`total_gross_cents` is `straight_cash_cents` plus
    `service_charge_wages_cents` plus `overtime_premium_cents` plus `topup_cents`
    plus `correction_applied_cents`."

    Design: Difficulty/combinatorial_formula/pay_line_regular_rate_excludes_topup_pinned_order
    """
    world = setup_new_york_overtime_world()

    compute_period(world["pay_period"]["id"])
    line = _sole_line(world["pay_period"]["id"])

    assert line["tipped_employee_qualified"] is True
    assert line["tips_available_cents"] == 40000
    assert line["tip_credit_cents"] == 17417, (
        "the residual 71250 - 45000 - 6000 - 2833 binds below both the 22500 "
        "per-hour ceiling and the 40000 of tips actually available"
    )
    assert line["topup_cents"] == 0, (
        "the residual was fully consumed by the credit, so nothing is left to add"
    )
    assert line["total_gross_cents"] == 53833
    assert line["reported_tips_cents"] == 40000
