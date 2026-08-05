"""Weekly earnings-statement settlement: per-diem stipend variants, per-line pay
rounding, the margin-floor bill uplift, the stipend cap, and effective-dated locality
selection."""
from test_helpers import TEST_USERS, assert_money_partition
from test_helpers.fixtures import (
    setup_active_assignment, submit_timesheet, approve_timesheet,
    statement_for_timesheet, get_assignment_data, get_clinician_data,
)

RECRUITER = TEST_USERS["recruiter_headers"]


# --- Difficulty: stipend FULL_WEEK_ACCRUAL vs DAILY_PRORATED on the earnings statement ---
def test_stipend_full_week_accrual_branch(api):
    """PRD §3.6: "When worked hours are at least 32 — the full-week stipend threshold, an
    inclusive comparison — the stipend_variant is FULL_WEEK_ACCRUAL and the stipend is the
    smaller of the daily total multiplied by seven calendar days or the weekly cap of
    250000 cents; a full week accrues all seven days of lodging and M&IE regardless of how
    many days were actually worked."

    Design: Difficulty/dual_variant_calc/stipend_full_week_accrual_vs_daily_prorated_on_earnings_statement
    """
    ctx = setup_active_assignment(api, clock="2026-06-21")
    ts = submit_timesheet(api, ctx.asg_id, "2026-06-07", [0, 12, 12, 8, 0, 0, 0], ctx.clin_id)
    approve_timesheet(api, ts["id"], ctx.fac_id)
    st = statement_for_timesheet(api, ts["id"])
    assert st["stipend_variant"] == "FULL_WEEK_ACCRUAL"
    assert st["non_taxable_stipend_cents"] == 160300
    assert st["taxable_wages_cents"] == 166400
    assert st["burden_cents"] == 30784
    assert st["total_pay_cost_cents"] == 357484


def test_stipend_daily_prorated_branch(api):
    """PRD §3.6: "When worked hours are below 32 the stipend_variant is DAILY_PRORATED and
    the stipend is the smaller of the daily total multiplied by days_worked or the same
    250000-cent cap, so at identical daily rates a short week yields a strictly smaller
    stipend."

    Design: Difficulty/dual_variant_calc/stipend_full_week_accrual_vs_daily_prorated_on_earnings_statement
    """
    ctx = setup_active_assignment(api, clock="2026-06-21")
    ts = submit_timesheet(api, ctx.asg_id, "2026-06-14", [0, 12, 12, 7.5, 0, 0, 0], ctx.clin_id)
    approve_timesheet(api, ts["id"], ctx.fac_id)
    st = statement_for_timesheet(api, ts["id"])
    assert st["stipend_variant"] == "DAILY_PRORATED"
    assert st["non_taxable_stipend_cents"] == 68700
    assert st["taxable_wages_cents"] == 163800
    assert st["burden_cents"] == 30303
    assert st["total_pay_cost_cents"] == 262803


# --- Difficulty: pay cost rounds per line before summation (mode b) ---
def test_taxable_wages_rounds_per_line_before_summation(api):
    """PRD §3.6: "Each pay line is rounded to whole cents before the lines are summed. The
    regular pay is regular_hours multiplied by base_pay_rate_cents_per_hour, rounded half
    up. The overtime pay is overtime_hours multiplied by base_pay_rate_cents_per_hour
    multiplied by the overtime multiplier of 1.5, rounded half up. ... The
    taxable_wages_cents is the sum of those three rounded lines plus the stipend amount
    when it was routed to wages (that is, when the tax home is unverified)."

    Design: Difficulty/combinatorial_formula/weekly_pay_cost_rounds_per_line_before_summation_mode_b
    """
    ctx = setup_active_assignment(api, clock="2026-06-14",
                                  assignment_overrides={"base_pay_rate_cents_per_hour": 3333})
    ts = submit_timesheet(api, ctx.asg_id, "2026-06-07", [0, 13, 12, 12, 0.5, 0, 0], ctx.clin_id)
    approve_timesheet(api, ts["id"], ctx.fac_id)
    st = statement_for_timesheet(api, ts["id"])
    assert st["taxable_wages_cents"] == 126655  # NOT 126654 (per-line 121655 + 5000)
    assert st["non_taxable_stipend_cents"] == 160300
    assert st["burden_cents"] == 23431
    assert st["total_pay_cost_cents"] == 310386
    assert st["gross_bill_cents"] == 532000 and st["margin_uplift_applied"] is False


# --- Difficulty: bill / margin-floor uplift with pinned evaluation order (mode c) ---
def test_weekly_bill_uplifted_to_hold_margin_floor(api):
    """PRD §3.6: "The smallest bill that holds the 22 percent margin floor — the required
    bill — is the total_pay_cost_cents multiplied by 100 and integer-ceiling-divided by 78
    (the exact integer form of dividing the pay cost by 0.78, so the floor is never
    undershot). The gross_bill_cents is the larger of contracted_bill_cents and that
    required bill, and margin_uplift_applied is true exactly when the gross bill was lifted
    above the contracted bill."

    Design: Difficulty/combinatorial_formula/weekly_bill_margin_floor_uplift_pinned_evaluation_order_mode_c
    """
    ctx = setup_active_assignment(api, clock="2026-06-14")
    ts = submit_timesheet(api, ctx.asg_id, "2026-06-07", [0, 11, 11, 11, 0, 0, 0], ctx.clin_id)
    approve_timesheet(api, ts["id"], ctx.fac_id)
    st = statement_for_timesheet(api, ts["id"])
    assert st["contracted_bill_cents"] == 462000
    assert st["gross_bill_cents"] == 466213
    assert st["margin_uplift_applied"] is True


def test_weekly_uplifted_statement_holds_money_partition(api):
    """PRD §3.6: "Finally gross_margin_cents is gross_bill_cents minus total_pay_cost_cents,
    and margin_pct is gross_margin_cents divided by gross_bill_cents, rounded half up to
    four decimal places. On every statement the money partition holds: the gross bill
    equals the pay cost plus the gross margin."

    Design: Difficulty/combinatorial_formula/weekly_bill_margin_floor_uplift_pinned_evaluation_order_mode_c
    """
    ctx = setup_active_assignment(api, clock="2026-06-14")
    ts = submit_timesheet(api, ctx.asg_id, "2026-06-07", [0, 11, 11, 11, 0, 0, 0], ctx.clin_id)
    approve_timesheet(api, ts["id"], ctx.fac_id)
    st = statement_for_timesheet(api, ts["id"])
    assert st["total_pay_cost_cents"] == 363646
    assert st["gross_margin_cents"] == 102567
    assert st["margin_pct"] == 0.22
    assert_money_partition(st)


# --- Difficulty: stipend threshold is inclusive at exactly 32 worked hours ---
def test_stipend_inclusive_at_exactly_32_hours(api):
    """PRD §3.6: "When worked hours are at least 32 — the full-week stipend threshold, an
    inclusive comparison — the stipend_variant is FULL_WEEK_ACCRUAL and the stipend is the
    smaller of the daily total multiplied by seven calendar days or the weekly cap of
    250000 cents"

    Design: Difficulty/boundary_precision_check/stipend_threshold_is_inclusive_at_exactly_32_worked_hours
    """
    ctx = setup_active_assignment(api, clock="2026-06-21")
    ts = submit_timesheet(api, ctx.asg_id, "2026-06-07", [0, 12, 12, 8, 0, 0, 0], ctx.clin_id)
    approve_timesheet(api, ts["id"], ctx.fac_id)
    st = statement_for_timesheet(api, ts["id"])
    assert st["stipend_variant"] == "FULL_WEEK_ACCRUAL" and st["non_taxable_stipend_cents"] == 160300


def test_stipend_below_32_hours_is_daily_prorated(api):
    """PRD §3.6: "When worked hours are below 32 the stipend_variant is DAILY_PRORATED and
    the stipend is the smaller of the daily total multiplied by days_worked or the same
    250000-cent cap"
    PRD §3.6: "guaranteed_hours_consumed increases by the smaller of the week's worked
    hours (regular_hours plus overtime_hours) or the contract's weekly_guaranteed_hours,
    and guaranteed_hours_remaining decreases by that same amount."

    Design: Difficulty/boundary_precision_check/stipend_threshold_is_inclusive_at_exactly_32_worked_hours
    """
    ctx = setup_active_assignment(api, clock="2026-06-21")
    ts_at = submit_timesheet(api, ctx.asg_id, "2026-06-07", [0, 12, 12, 8, 0, 0, 0], ctx.clin_id)
    approve_timesheet(api, ts_at["id"], ctx.fac_id)
    ts_below = submit_timesheet(api, ctx.asg_id, "2026-06-14", [0, 12, 12, 7.99, 0, 0, 0], ctx.clin_id)
    approve_timesheet(api, ts_below["id"], ctx.fac_id)
    st = statement_for_timesheet(api, ts_below["id"])
    assert st["stipend_variant"] == "DAILY_PRORATED" and st["non_taxable_stipend_cents"] == 68700
    assert st["taxable_wages_cents"] == 166348 and st["burden_cents"] == 30774
    assert st["total_pay_cost_cents"] == 265822 and st["gross_bill_cents"] == 447860
    assert st["margin_uplift_applied"] is False
    asg = get_assignment_data(api, ctx.asg_id)
    assert asg["guaranteed_hours_consumed"] == 63.99 and asg["guaranteed_hours_remaining"] == 404.01


# --- Corner: contractor 1099 carries no burden and a taxable stipend ---
def test_contractor_1099_no_burden_and_taxable_stipend(api):
    """PRD §3.6: "The burden_cents is the taxable_wages_cents multiplied by 0.185 and
    rounded half up for a W2_EMPLOYEE, and 0 for a CONTRACTOR_1099."
    PRD §3.6: "when it is false, non_taxable_stipend_cents is 0 and the stipend amount is
    instead added into taxable wages."

    Design: Corner/calculations/corner_contractor_1099_carries_no_burden_and_taxable_stipend
    """
    ctx = setup_active_assignment(api, clock="2026-06-14", clinician_overrides={
        "full_name": "Cara Nunez", "employment_type": "CONTRACTOR_1099", "tax_home_verified": False})
    ts = submit_timesheet(api, ctx.asg_id, "2026-06-07", [0, 12, 12, 12, 0, 0, 0], ctx.clin_id)
    approve_timesheet(api, ts["id"], ctx.fac_id)
    st = statement_for_timesheet(api, ts["id"])
    assert st["stipend_variant"] == "FULL_WEEK_ACCRUAL" and st["non_taxable_stipend_cents"] == 0
    assert st["taxable_wages_cents"] == 347500
    assert st["burden_cents"] == 0 and st["total_pay_cost_cents"] == 347500
    assert st["gross_bill_cents"] == 504000 and st["gross_margin_cents"] == 156500
    assert st["margin_pct"] == 0.3105
    clin = get_clinician_data(api, ctx.clin_id)
    assert clin["ytd_taxable_wages_cents"] == 347500 and clin["ytd_nontaxable_stipend_cents"] == 0
    asg = get_assignment_data(api, ctx.asg_id)
    assert asg["projected_pay_cost_cents"] == 4517500 and asg["projected_margin_pct"] == 0.3105


# --- Corner: stipend weekly cap truncates a high locality rate ---
def test_stipend_weekly_cap_truncates_high_locality(api):
    """PRD §3.6: "the stipend is the smaller of the daily total multiplied by seven
    calendar days or the weekly cap of 250000 cents"

    Design: Corner/calculations/corner_stipend_weekly_cap_truncates_a_high_locality_rate
    """
    ctx = setup_active_assignment(
        api, clock="2026-06-14",
        per_diems=[{"locality_code": "ASP-AK", "state_code": "AK",
                    "daily_lodging_cents": 40000, "daily_mie_cents": 5000, "effective_from": "2026-01-01"}],
        facility_overrides={"name": "North Slope Clinic", "state_code": "AK",
                            "per_diem_locality_code": "ASP-AK", "is_compact_member": True},
        assignment_overrides={"bill_rate_cents_per_hour": 20000})
    ts = submit_timesheet(api, ctx.asg_id, "2026-06-07", [0, 12, 12, 12, 0, 0, 0], ctx.clin_id)
    approve_timesheet(api, ts["id"], ctx.fac_id)
    st = statement_for_timesheet(api, ts["id"])
    assert st["stipend_variant"] == "FULL_WEEK_ACCRUAL" and st["non_taxable_stipend_cents"] == 250000
    assert st["taxable_wages_cents"] == 187200 and st["burden_cents"] == 34632
    assert st["total_pay_cost_cents"] == 471832
    assert st["contracted_bill_cents"] == 720000 and st["gross_bill_cents"] == 720000
    assert st["margin_uplift_applied"] is False and st["gross_margin_cents"] == 248168
    assert st["margin_pct"] == 0.3447


# --- Corner: per-diem locality selection takes latest row effective on or before the week ---
def test_per_diem_selection_uses_latest_row_effective_on_or_before_week(api):
    """PRD §3.6: "among all PerDiemLocality rows whose locality_code equals the facility's
    per_diem_locality_code and whose effective_from is on or before the basis date (the
    week_start_date), the winner is the one with the latest effective_from, breaking ties
    by earliest created_at."

    Design: Corner/calculations/corner_per_diem_locality_selection_takes_latest_row_effective_on_or_before_the_week
    """
    ctx = setup_active_assignment(
        api, clock="2026-06-21",
        per_diems=[{},  # PHX-AZ effective 2026-01-01 at 22900/day
                   {"effective_from": "2026-06-14", "daily_lodging_cents": 16000, "daily_mie_cents": 8000}])
    ts_old = submit_timesheet(api, ctx.asg_id, "2026-06-07", [0, 12, 12, 12, 0, 0, 0], ctx.clin_id)
    approve_timesheet(api, ts_old["id"], ctx.fac_id)
    ts_new = submit_timesheet(api, ctx.asg_id, "2026-06-14", [0, 12, 12, 12, 0, 0, 0], ctx.clin_id)
    approve_timesheet(api, ts_new["id"], ctx.fac_id)
    st_old = statement_for_timesheet(api, ts_old["id"])
    assert st_old["non_taxable_stipend_cents"] == 160300 and st_old["total_pay_cost_cents"] == 382132
    assert st_old["gross_bill_cents"] == 504000 and st_old["gross_margin_cents"] == 121868
    st_new = statement_for_timesheet(api, ts_new["id"])
    assert st_new["non_taxable_stipend_cents"] == 168000 and st_new["total_pay_cost_cents"] == 389832
    assert st_new["gross_bill_cents"] == 504000 and st_new["gross_margin_cents"] == 114168
    assert st_new["margin_pct"] == 0.2265
