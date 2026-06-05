"""Cost calculation compliance: monthly employee cost, per-paycheck deduction,
carrier-premium proration rounding, and voluntary-life rate-per-1000.

Covers Difficulty/combinatorial_formula and Difficulty/dual_variant_calc (carrier line)
plus Corner/calculations correct-result / constants-applied claims.
"""
from test_helpers import (
    validate_success, get_success_data,
    setup_eligible_employee, create_offering, create_tier, create_draft_enrollment,
    activate_enrollment, employee_version, list_carrier_feed_records,
    setup_active_medical_enrollment,
    api_client as api,
    TEST_USERS,
)

_ADMIN = TEST_USERS["benefits_admin_headers"]


def test_per_paycheck_deduction_biweekly_branch():
    """PRD §3.5: "The number of pay periods in a year is twenty-four when the employee's
    payroll_schedule is SEMI_MONTHLY and twenty-six when it is BIWEEKLY. The annual
    employee cost is monthly_employee_cost_cents multiplied by twelve, and
    per_paycheck_deduction_cents is that annual cost divided by the number of pay periods
    in the year, rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/per_paycheck_deduction_tier_and_schedule_branch
    """
    emp = setup_eligible_employee(payroll_schedule="BIWEEKLY")
    off = create_offering(benefit_type="MEDICAL", name="Gold PPO")
    tier = create_tier(off["id"], coverage_level="EMPLOYEE_ONLY",
                       monthly_premium_cents=60000, employer_contribution_pct=0.70)
    enr = create_draft_enrollment(emp["id"], tier["id"], coverage_start_date="2026-02-01")
    ev = employee_version(emp["id"])
    data = validate_success(api.activate_enrollment(
        enr["id"], {"expected_employee_version": ev}, _ADMIN))
    assert data["monthly_employee_cost_cents"] == 18000, data
    # round_half_up(18000 * 12 / 26) = round_half_up(8307.69) = 8308
    assert data["per_paycheck_deduction_cents"] == 8308, data


def test_per_paycheck_deduction_semi_monthly_branch():
    """PRD §3.5: "The number of pay periods in a year is twenty-four when the employee's
    payroll_schedule is SEMI_MONTHLY and twenty-six when it is BIWEEKLY. The annual
    employee cost is monthly_employee_cost_cents multiplied by twelve, and
    per_paycheck_deduction_cents is that annual cost divided by the number of pay periods
    in the year, rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/per_paycheck_deduction_tier_and_schedule_branch
    """
    emp = setup_eligible_employee(payroll_schedule="SEMI_MONTHLY")
    off = create_offering(benefit_type="MEDICAL", name="Gold PPO")
    tier = create_tier(off["id"], coverage_level="EMPLOYEE_ONLY",
                       monthly_premium_cents=60000, employer_contribution_pct=0.70)
    enr = create_draft_enrollment(emp["id"], tier["id"], coverage_start_date="2026-02-01")
    ev = employee_version(emp["id"])
    data = validate_success(api.activate_enrollment(
        enr["id"], {"expected_employee_version": ev}, _ADMIN))
    assert data["monthly_employee_cost_cents"] == 18000, data
    # 18000 * 12 / 24 = 9000
    assert data["per_paycheck_deduction_cents"] == 9000, data


def test_carrier_premium_round_per_line_then_sum_semi_monthly():
    """PRD §3.8: "The reconciled_monthly_premium_cents is the sum of these two
    already-rounded component lines. Each component line is rounded to whole cents first
    and the rounded lines are then added — this round-per-line-then-sum order is pinned
    and is not the same as prorating the combined premium and rounding once at the end,
    because the two can differ by a cent at certain proration ratios."

    Design: Difficulty/combinatorial_formula/carrier_reconcile_rounding_order_pinned
    """
    emp = setup_eligible_employee(payroll_schedule="SEMI_MONTHLY",
                                  clock_after="2026-03-16T00:00:00Z")
    off = create_offering(benefit_type="MEDICAL", name="Gold PPO")
    tier = create_tier(off["id"], coverage_level="EMPLOYEE_ONLY",
                       monthly_premium_cents=60000, employer_contribution_pct=0.70)
    enr = create_draft_enrollment(emp["id"], tier["id"], coverage_start_date="2026-03-16")
    ev = employee_version(emp["id"])
    get_success_data(api.activate_enrollment(
        enr["id"], {"expected_employee_version": ev}, _ADMIN))
    records, _ = list_carrier_feed_records(enrollment_id=enr["id"], transaction_set="ADD")
    assert len(records) == 1, records
    # prorated_employer round(42000*16/31)=21677 + prorated_employee round(18000*16/31)=9290 = 30967
    assert records[0]["reconciled_monthly_premium_cents"] == 30967, records[0]


def test_carrier_premium_diverges_from_sum_then_round():
    """PRD §3.8: "this round-per-line-then-sum order is pinned and is not the same as
    prorating the combined premium and rounding once at the end, because the two can
    differ by a cent at certain proration ratios."

    Design: Difficulty/dual_variant_calc/carrier_premium_round_per_line_vs_sum_then_round
    """
    emp = setup_eligible_employee(payroll_schedule="BIWEEKLY",
                                  clock_after="2026-03-16T00:00:00Z")
    off = create_offering(benefit_type="MEDICAL", name="Gold PPO")
    tier = create_tier(off["id"], coverage_level="EMPLOYEE_ONLY",
                       monthly_premium_cents=60000, employer_contribution_pct=0.70)
    enr = create_draft_enrollment(emp["id"], tier["id"], coverage_start_date="2026-03-16")
    ev = employee_version(emp["id"])
    get_success_data(api.activate_enrollment(
        enr["id"], {"expected_employee_version": ev}, _ADMIN))
    records, _ = list_carrier_feed_records(enrollment_id=enr["id"], transaction_set="ADD")
    assert len(records) == 1, records
    assert records[0]["reconciled_monthly_premium_cents"] == 30967, records[0]
    # sum-then-round = round(60000*16/31) = round(30967.7) = 30968; the pinned order rejects this
    assert records[0]["reconciled_monthly_premium_cents"] != 30968, records[0]


def test_carrier_premium_component_lines_sum_to_pinned_value():
    """PRD §3.8: "The prorated employer line is the employer monthly share multiplied by
    the covered days and divided by the month's day count, rounded half up to whole cents;
    the prorated employee line is computed the same way from the employee monthly share.
    The reconciled_monthly_premium_cents is the sum of these two already-rounded component
    lines."

    Design: Difficulty/combinatorial_formula/carrier_reconcile_rounding_order_pinned
    """
    emp = setup_eligible_employee(payroll_schedule="SEMI_MONTHLY",
                                  clock_after="2026-03-16T00:00:00Z")
    off = create_offering(benefit_type="MEDICAL", name="Gold PPO")
    tier = create_tier(off["id"], coverage_level="EMPLOYEE_ONLY",
                       monthly_premium_cents=60000, employer_contribution_pct=0.70)
    enr = create_draft_enrollment(emp["id"], tier["id"], coverage_start_date="2026-03-16")
    ev = employee_version(emp["id"])
    get_success_data(api.activate_enrollment(
        enr["id"], {"expected_employee_version": ev}, _ADMIN))
    records, _ = list_carrier_feed_records(enrollment_id=enr["id"], transaction_set="ADD")
    assert len(records) == 1, records
    # prorated_employer 21677 + prorated_employee 9290 == 30967 (round-per-line-then-sum)
    assert records[0]["reconciled_monthly_premium_cents"] == 21677 + 9290, records[0]


def test_carrier_premium_value_under_pinned_order():
    """PRD §3.8: "The reconciled_monthly_premium_cents is the sum of these two
    already-rounded component lines. Each component line is rounded to whole cents first
    and the rounded lines are then added — this round-per-line-then-sum order is pinned and
    is not the same as prorating the combined premium and rounding once at the end, because
    the two can differ by a cent at certain proration ratios."

    Design: Difficulty/dual_variant_calc/carrier_premium_round_per_line_vs_sum_then_round
    """
    emp = setup_eligible_employee(payroll_schedule="SEMI_MONTHLY",
                                  clock_after="2026-03-16T00:00:00Z")
    off = create_offering(benefit_type="MEDICAL", name="Gold PPO")
    tier = create_tier(off["id"], coverage_level="EMPLOYEE_ONLY",
                       monthly_premium_cents=60000, employer_contribution_pct=0.70)
    enr = create_draft_enrollment(emp["id"], tier["id"], coverage_start_date="2026-03-16")
    ev = employee_version(emp["id"])
    get_success_data(api.activate_enrollment(
        enr["id"], {"expected_employee_version": ev}, _ADMIN))
    records, _ = list_carrier_feed_records(enrollment_id=enr["id"], transaction_set="ADD")
    assert len(records) == 1, records
    assert records[0]["reconciled_monthly_premium_cents"] == 30967, records[0]


def test_full_month_coverage_no_proration_carrier_premium():
    """PRD §3.8: "let the number of covered days be that day count minus the day-of-month
    of the coverage_start_date plus one. ... The prorated employer line is the employer
    monthly share multiplied by the covered days and divided by the month's day count,
    rounded half up to whole cents; the prorated employee line is computed the same way
    from the employee monthly share."

    Design: Corner/calculations/full_month_no_proration_carrier_premium
    """
    emp = setup_eligible_employee(payroll_schedule="SEMI_MONTHLY",
                                  clock_after="2026-02-01T00:00:00Z")
    off = create_offering(benefit_type="MEDICAL", name="Gold PPO")
    tier = create_tier(off["id"], coverage_level="EMPLOYEE_ONLY",
                       monthly_premium_cents=60000, employer_contribution_pct=0.70)
    enr = create_draft_enrollment(emp["id"], tier["id"], coverage_start_date="2026-02-01")
    ev = employee_version(emp["id"])
    get_success_data(api.activate_enrollment(
        enr["id"], {"expected_employee_version": ev}, _ADMIN))
    records, _ = list_carrier_feed_records(enrollment_id=enr["id"], transaction_set="ADD")
    assert len(records) == 1, records
    # Day-1 start: covered days == days in month, so no proration -> full 60000.
    assert records[0]["reconciled_monthly_premium_cents"] == 60000, records[0]


def test_voluntary_life_monthly_cost_rate_per_1000():
    """PRD §3.5: "For a voluntary-life enrollment, the number of one-thousand-dollar
    coverage units is the enrollment's coverage_amount_cents divided by one hundred
    thousand, and monthly_employee_cost_cents is that unit count multiplied by the tier's
    rate_per_1000_monthly_cents, rounded half up to whole cents."

    Design: Corner/calculations/voluntary_life_premium_rate_per_1000
    """
    emp = setup_eligible_employee()
    off = create_offering(benefit_type="VOLUNTARY_LIFE", name="Voluntary Life",
                          requires_eoi=False, guaranteed_issue_amount_cents=50000000)
    tier = create_tier(off["id"], coverage_level="EMPLOYEE_ONLY",
                       monthly_premium_cents=1, employer_contribution_pct=0.0,
                       rate_per_1000_monthly_cents=25)
    enr = create_draft_enrollment(emp["id"], tier["id"], coverage_start_date="2026-02-01",
                                  coverage_amount_cents=20000000)
    ev = employee_version(emp["id"])
    data = validate_success(api.activate_enrollment(
        enr["id"], {"expected_employee_version": ev}, _ADMIN))
    # 20000000 / 100000 = 200 units * 25 = 5000
    assert data["monthly_employee_cost_cents"] == 5000, data
