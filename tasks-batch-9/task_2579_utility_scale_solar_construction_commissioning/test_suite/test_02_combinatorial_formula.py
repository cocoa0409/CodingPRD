"""Two multi-term formulas whose evaluation order is part of the contract.

Wage restitution rounds each payroll line to whole cents before the lines are
summed, so the total differs by a cent from the round-once answer. The
substantial-completion settlement runs seven steps whose terms reference one
another, so any reordering produces a different payment.
"""

from test_helpers.assertions import (
    assert_cents,
    assert_compliance_run,
    assert_project_state,
    assert_ratio,
    assert_waterfall,
)
from test_helpers.fixtures import (
    add_change_order,
    append_interval,
    certify_milestone,
    claim_milestone,
    create_payroll_week,
    create_project,
    create_punch_item,
    decide_milestone,
    energized_project,
    finalize_test,
    post_labor_entry,
    read_payroll_week,
    read_project,
    read_settlement_summary,
    run_labor_compliance,
    schedule_commissioning_test,
    set_clock,
)

# Three under-prevailing lines. Each hourly shortfall is the prevailing rate
# less paid plus fringe: 5000 - 4925 == 75, 5000 - 4945 == 55, 5000 - 4955 == 45.
UNDERPAID_LINES = (
    {"worker_ref": "W-201", "classification": "IRONWORKER", "hours": 10.10, "paid_rate_cents": 4000, "fringe_rate_cents": 925, "prevailing_rate_cents": 5000, "work_date": "2026-08-03"},
    {"worker_ref": "W-202", "classification": "IRONWORKER", "hours": 11.95, "paid_rate_cents": 4000, "fringe_rate_cents": 945, "prevailing_rate_cents": 5000, "work_date": "2026-08-04"},
    {"worker_ref": "W-203", "classification": "OPERATOR", "hours": 7.37, "paid_rate_cents": 4200, "fringe_rate_cents": 755, "prevailing_rate_cents": 5000, "work_date": "2026-08-05"},
)


def _remediable_week(api):
    """A REMEDIABLE project whose open week holds the three deficient lines."""
    project = create_project(api, name="Dry Wash", prevailing_wage_election="REMEDIABLE")
    week = create_payroll_week(api, project["id"], week_start_date="2026-08-03")
    lines = [
        post_labor_entry(api, week["id"], is_apprentice=False, **spec)
        for spec in UNDERPAID_LINES
    ]
    return project, week, lines


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/prevailing_wage_restitution_rounds_per_entry_before_summing
# ---------------------------------------------------------------------------
def test_each_line_carries_its_own_shortfall_and_rounded_restitution(api):
    """Every posted line rounds its own hourly shortfall times hours to whole cents.

    PRD 3.8: "`restitution_cents` is that hourly shortfall multiplied by the
    line's `hours`, rounded half up to whole cents while the line remains
    `POSTED`; it becomes 0 once the line is voided."

    Design: Difficulty/combinatorial_formula/prevailing_wage_restitution_rounds_per_entry_before_summing
    """
    _project, _week, lines = _remediable_week(api)

    # 75 x 10.10 == 757.50 -> 758; 55 x 11.95 == 657.25 -> 657; 45 x 7.37 == 331.65 -> 332.
    assert lines[0]["shortfall_cents_per_hour"] == 75
    assert_cents(lines[0]["restitution_cents"], 758, "restitution_cents of W-201")
    assert lines[1]["shortfall_cents_per_hour"] == 55
    assert_cents(lines[1]["restitution_cents"], 657, "restitution_cents of W-202")
    assert lines[2]["shortfall_cents_per_hour"] == 45
    assert_cents(lines[2]["restitution_cents"], 332, "restitution_cents of W-203")


def test_the_project_total_sums_the_already_rounded_per_line_amounts(api):
    """The owed total is 1747 cents, not the 1746 the round-once order produces.

    PRD 3.8: "**The rounding order is pinned**: each line's restitution is
    rounded half up to whole cents *first*, and only then are the per-line
    amounts summed into the project's `wage_restitution_owed_cents`."

    Design: Difficulty/combinatorial_formula/prevailing_wage_restitution_rounds_per_entry_before_summing
    """
    project, _week, _lines = _remediable_week(api)

    run = run_labor_compliance(api, project["id"])

    # Raw products sum to 1746.40, which would round to 1746.
    assert_compliance_run(run, wage_restitution_owed_cents=1747)
    assert run["wage_restitution_owed_cents"] != 1746


def test_the_liquidated_damages_uplift_follows_the_pinned_total(api):
    """A twenty percent uplift on 1747 cents is 349, and a cent owed disqualifies.

    PRD 3.8: "From that total, `wage_liquidated_damages_cents` is the project's
    `wage_restitution_owed_cents` multiplied by 0.20 — a twenty percent uplift —
    rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/prevailing_wage_restitution_rounds_per_entry_before_summing
    """
    project, week, _lines = _remediable_week(api)

    run = run_labor_compliance(api, project["id"])

    # 1747 x 0.20 == 349.40 -> 349. The 1746 answer would give 349.20 -> 349
    # as well, but the owed figure itself is what the ladder settles on.
    assert_compliance_run(
        run,
        wage_restitution_owed_cents=1747,
        wage_liquidated_damages_cents=349,
        tax_credit_status="DISQUALIFIED",
    )
    ledger = read_payroll_week(api, week["id"])
    assert_ratio(ledger["total_hours"], 29.42, "total_hours")
    assert ledger["entry_count"] == 3


# ---------------------------------------------------------------------------
# Difficulty/combinatorial_formula/substantial_completion_settlement_waterfall_order_pinned
# ---------------------------------------------------------------------------
def _settled_project(api):
    """Walk a plant to substantial-completion certification twelve days late."""
    rows = energized_project(api)
    project_id = rows["project"]["id"]

    test = schedule_commissioning_test(
        api,
        project_id,
        test_type="CAPACITY",
        correction_variant="WEATHER_CORRECTED",
        scheduled_at="2026-08-10T03:00:00Z",
    )
    append_interval(api, test["id"], "2026-08-10T03:00:00Z", 850, 76.50, ambient_c=30, wind_m_s=3.0)
    append_interval(api, test["id"], "2026-08-10T03:15:00Z", 900, 81.00, ambient_c=32, wind_m_s=4.0)
    passed = finalize_test(api, test["id"])
    assert passed["status"] == "PASSED"

    item = create_punch_item(
        api,
        project_id,
        title="Tracker row 4 grout touch-up",
        category="MECHANICAL",
        severity="MAJOR",
        estimated_cost_cents=200000,
        block_id=rows["block"]["id"],
    )
    add_change_order(api, project_id, 1000000, reason="Added access road culvert")

    certify_milestone(api, project_id, "MECHANICAL_COMPLETION")
    claim_milestone(api, project_id, "SUBSTANTIAL_COMPLETION")
    set_clock(api, "2026-08-13T00:00:00Z")
    certified = decide_milestone(api, project_id, "SUBSTANTIAL_COMPLETION", "CERTIFY")
    return project_id, item, certified


def test_the_ld_ceiling_and_retainage_both_key_off_the_adjusted_contract(api):
    """A change order lifts the contract to 11000000, and both derived caps follow it.

    PRD 3.9: "The adjusted contract value is the project's
    `contract_value_cents` plus its `approved_change_order_cents`."

    Design: Difficulty/combinatorial_formula/substantial_completion_settlement_waterfall_order_pinned
    """
    project_id, _item, _certified = _settled_project(api)

    summary = read_settlement_summary(api, project_id)

    # 11000000 x 0.05 == 550000 for both the ceiling and the retainage.
    assert_waterfall(
        summary,
        adjusted_contract_cents=11000000,
        ld_cap_cents=550000,
        retainage_held_cents=550000,
    )


def test_liquidated_damages_are_clamped_by_the_ceiling_not_by_raw_exposure(api):
    """Twelve days at 50000 cents raises 600000, which the 550000 ceiling clamps.

    PRD 3.9: "`ld_assessed_cents` is the lesser of `delay_days` multiplied by
    `ld_per_day_cents`, and the ceiling from step 2."

    Design: Difficulty/combinatorial_formula/substantial_completion_settlement_waterfall_order_pinned
    """
    project_id, _item, certified = _settled_project(api)

    assert_waterfall(certified, delay_days=12, ld_assessed_cents=550000)
    assert certified["ld_assessed_cents"] < 12 * 50000
    # The ceiling taken on the base contract would have been 500000 instead.
    assert_waterfall(read_settlement_summary(api, project_id), ld_cap_cents=550000)


def test_the_punchlist_holdback_is_one_and_a_half_times_the_open_estimate(api):
    """An open 200000 estimate withholds 300000, under the retainage clamp.

    PRD 3.9: "`punchlist_holdback_cents` is the lesser of two amounts: the sum
    of `estimated_cost_cents` across the project's punch-list items whose
    `status` is `OPEN` or `CLOSURE_SUBMITTED` at this instant, multiplied by a
    holdback multiplier of 1.5 — one and a half times the owner's estimate — and
    rounded half up to whole cents; and the `retainage_held_cents` from step 5."

    Design: Difficulty/combinatorial_formula/substantial_completion_settlement_waterfall_order_pinned
    """
    project_id, _item, certified = _settled_project(api)

    assert_waterfall(certified, punchlist_holdback_cents=300000, retainage_held_cents=550000)
    assert read_project(api, project_id)["open_punch_item_count"] == 1


def test_the_payment_due_is_the_adjusted_contract_less_the_three_withholdings(api):
    """The seventh step lands on 9600000, and final payment waits for acceptance.

    PRD 3.9: "`sc_payment_due_cents` is the adjusted contract value less
    `retainage_held_cents`, less `ld_assessed_cents`, less
    `punchlist_holdback_cents`, floored at 0."

    Design: Difficulty/combinatorial_formula/substantial_completion_settlement_waterfall_order_pinned
    """
    project_id, _item, certified = _settled_project(api)

    # 11000000 - 550000 - 550000 - 300000 == 9600000.
    assert_waterfall(certified, sc_payment_due_cents=9600000, final_payment_cents=0)
    assert_project_state(certified, milestone_state="SC_CERTIFIED")

    summary = read_settlement_summary(api, project_id)
    assert_cents(
        summary["adjusted_contract_cents"]
        - summary["retainage_held_cents"]
        - summary["ld_assessed_cents"]
        - summary["punchlist_holdback_cents"],
        9600000,
        "the seventh step recomputed by hand",
    )
    assert_waterfall(summary, sc_payment_due_cents=9600000, final_payment_cents=0)
