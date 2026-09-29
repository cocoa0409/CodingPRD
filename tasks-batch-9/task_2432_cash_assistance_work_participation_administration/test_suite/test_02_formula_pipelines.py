"""Multi-step formulas whose step order changes the resulting integers."""
from test_helpers import assertions as asrt
from test_helpers import fixtures as fx


def _large_household_case_at_conciliation_deadline(api):
    """A size-11 case with no income, sanctionable today."""
    context = fx.build_active_case(
        api,
        household_overrides={
            "head_of_household_name": "Large Household",
            "household_size": 11,
        },
        incomes=(),
    )
    episode = fx.open_episode(
        api, context.case_id, allegation_reason="REFUSED_ASSIGNMENT"
    )
    conciliating = fx.start_conciliation(api, episode["id"])
    fx.advance_clock_to_deadline(api, conciliating)
    return context, episode["id"]


def test_determined_grant_caps_the_ratably_reduced_deficit(api):
    """PRD §3.2: "Step one establishes the **payment standard** for the household
    size: 26000 cents for a unit of one, 39000 for two, 49000 for three, 59000 for
    four, 68000 for five and 76000 for six; for a unit larger than six, the
    standard is the six-person figure of 76000 cents plus 7000 cents for each
    person beyond the sixth."
    PRD §3.2: "Step four caps that pre-sanction figure at a maximum grant of 90000
    cents, taking whichever is smaller."

    Design: Difficulty/combinatorial_formula/benefit_pipeline_order_ratable_then_cap_then_sanction_then_minimum
    """
    built = fx.build_determined_application(
        api,
        household_overrides={
            "head_of_household_name": "Large Household",
            "household_size": 11,
        },
        incomes=(),
    )
    application = fx.read_application(api, built["application"]["id"])

    asrt.assert_money(application["countable_income_cents"], 0, "countable income")
    asrt.assert_money(application["determined_benefit_cents"], 90000, "determined benefit")


def test_sanction_cut_applies_after_the_maximum_grant_cap(api):
    """PRD §3.2: "Step five computes the sanction cut as the capped figure
    multiplied by the sanction fraction, rounded half up to a whole cent, and
    subtracts that cut from the capped figure."
    PRD §3.7: "The case's `benefit_amount_cents` is then recomputed by the six-step
    grant formula of §3.2, using the case's frozen `household_size` and
    `countable_income_cents` together with the new sanction fraction."

    Design: Difficulty/combinatorial_formula/benefit_pipeline_order_ratable_then_cap_then_sanction_then_minimum
    """
    context, episode_id = _large_household_case_at_conciliation_deadline(api)

    fx.impose_sanction(api, episode_id)

    episode = fx.read_episode(api, episode_id)
    assert episode["sanction_level"] == 1
    asrt.assert_pct(episode["sanction_pct"], 0.25, "episode sanction_pct")
    asrt.assert_case_state(
        fx.read_case(api, context.case_id),
        benefit_status="ACTIVE",
        compliance_status="SANCTIONED",
        sanction_level=1,
        benefit_amount_cents=67500,
    )


def _rounding_order_application(api):
    """A retrospective application whose two sources each average to x.67."""
    return fx.build_determined_application(
        api,
        household_overrides={"head_of_household_name": "Rounding Order Household"},
        application_overrides={"budgeting_method": "RETROSPECTIVE"},
        incomes=(
            {
                "source_type": "EARNED",
                "gross_monthly_cents": 10000,
                "month_1_cents": 10000,
                "month_2_cents": 10001,
                "month_3_cents": 10001,
                "is_recurring": True,
                "verification_status": "VERIFIED",
            },
            {
                "source_type": "EARNED",
                "gross_monthly_cents": 20000,
                "month_1_cents": 20000,
                "month_2_cents": 20001,
                "month_3_cents": 20001,
                "is_recurring": True,
                "verification_status": "VERIFIED",
            },
        ),
    )


def test_retrospective_average_is_floored_per_source_before_summing(api):
    """PRD §3.2: "The rounding order here is pinned: each source is averaged and
    floored on its own first, and only then are the floored per-source figures
    added together."
    PRD §3.2: "Summing all three months across all sources and dividing once at the
    end is wrong and can differ by a cent."

    Design: Difficulty/combinatorial_formula/retrospective_average_floors_per_source_before_summing
    """
    built = _rounding_order_application(api)
    application = fx.read_application(api, built["application"]["id"])

    asrt.assert_money(application["countable_income_cents"], 9000, "countable income")
    assert application["status"] == "DETERMINED"


def test_per_source_flooring_propagates_into_the_determined_grant(api):
    """PRD §3.2: "Gross earned income is first reduced by a flat earned-income
    disregard of 12000 cents, floored at zero."
    PRD §3.2: "Half of whatever earned income survives that flat disregard is
    countable, rounded half up to a whole number of cents."
    PRD §3.2: "Step three applies the ratable reduction, multiplying the deficit by
    0.85 and rounding half up to a whole cent."

    Design: Difficulty/combinatorial_formula/retrospective_average_floors_per_source_before_summing
    """
    built = _rounding_order_application(api)
    application = fx.read_application(api, built["application"]["id"])

    asrt.assert_money(application["determined_benefit_cents"], 34000, "determined benefit")


def _fy2027_q1_case_participating_only_in_november(api):
    """One case issued for all three months of the quarter, meeting hours once."""
    context = fx.build_active_case(
        api,
        benefit_months=("2026-10", "2026-11", "2026-12"),
        household_overrides={"head_of_household_name": "WPR Household"},
        certification_start_month="2026-10",
        incomes=(
            {
                "source_type": "EARNED",
                "gross_monthly_cents": 40000,
                "is_recurring": True,
                "verification_status": "VERIFIED",
            },
            {
                "source_type": "UNEARNED_CHILD_SUPPORT",
                "gross_monthly_cents": 20000,
                "is_recurring": True,
                "verification_status": "VERIFIED",
            },
        ),
    )
    core = fx.create_active_assignment(
        api,
        context.case_id,
        activity_category="COMMUNITY_SERVICE",
        scheduled_weekly_hours=20,
        start_date="2026-10-01",
        end_date="2027-01-01",
    )
    non_core = fx.create_active_assignment(
        api,
        context.case_id,
        activity_category="JOB_SKILLS_TRAINING_DIRECT",
        scheduled_weekly_hours=10,
        start_date="2026-10-01",
        end_date="2027-01-01",
    )
    fx.credit_hours(api, core["id"], "2026-10", 40)
    fx.credit_hours(api, core["id"], "2026-11", 80)
    fx.credit_hours(api, non_core["id"], "2026-11", 40)
    return context


def test_quarterly_rates_come_from_the_adjusted_monthly_denominators(api):
    """PRD §3.10: "The all-families denominator is the total size of the adjusted
    denominators across the quarter's own three months, and the all-families
    numerator is the total size of the numerators across the same three months."
    PRD §3.10: "Quarter 1 is October, November and December of the calendar year
    *preceding* the fiscal year."

    Design: Difficulty/combinatorial_formula/wpr_five_stage_pipeline_with_unadjusted_caseload_for_the_credit
    """
    _fy2027_q1_case_participating_only_in_november(api)
    period = fx.open_period(
        api,
        fiscal_year=2027,
        quarter=1,
        prior_year_caseload=10.00,
        eligibility_change_caseload_effect=8.00,
    )

    fx.calculate_period(api, period["id"])

    calculated = fx.read_period(api, period["id"])
    assert calculated["status"] == "CALCULATED"
    asrt.assert_pct(calculated["wpr_all_families_pct"], 33.33, "wpr_all_families_pct")
    asrt.assert_pct(calculated["wpr_two_parent_pct"], 0.00, "wpr_two_parent_pct")


def test_caseload_reduction_credit_uses_the_unadjusted_raw_denominators(api):
    """PRD §3.10: "The `current_caseload` figure is the total size of the
    *unadjusted* raw denominators from stage one across the quarter's three months,
    divided by three, rounded half up to two decimal places."
    PRD §3.10: "The `caseload_reduction_credit_pct` is that raw decline less the
    `eligibility_change_caseload_effect`, rounded half up to two decimal places,
    then floored at 0.00 and capped at 50.00."
    PRD §3.10: "Finally `target_met` is true when `wpr_all_families_pct` is at or
    above the adjusted target, using an inclusive comparison, and false otherwise."

    Design: Difficulty/combinatorial_formula/wpr_five_stage_pipeline_with_unadjusted_caseload_for_the_credit
    """
    _fy2027_q1_case_participating_only_in_november(api)
    period = fx.open_period(
        api,
        fiscal_year=2027,
        quarter=1,
        prior_year_caseload=10.00,
        eligibility_change_caseload_effect=8.00,
    )

    fx.calculate_period(api, period["id"])

    calculated = fx.read_period(api, period["id"])
    asrt.assert_pct(calculated["current_caseload"], 1.00, "current_caseload")
    asrt.assert_pct(
        calculated["caseload_reduction_credit_pct"], 50.00, "caseload_reduction_credit_pct"
    )
    asrt.assert_pct(
        calculated["adjusted_target_all_families_pct"],
        0.00,
        "adjusted_target_all_families_pct",
    )
    assert calculated["target_met"] is True
