"""Formulas that fold several independent inputs, or pin an evaluation order."""

from test_helpers import (
    FC,
    BonusPlanScenario,
    assert_pct,
    assert_ratio,
    validate_success,
)


def _five_input_scenario() -> BonusPlanScenario:
    """Two metrics on different bands, two plan weights and one capped scorecard."""
    scenario = BonusPlanScenario()
    scenario.add_unit("EAST-A", name="East Region A")
    scenario.create_plan(
        plan_name="FY26 Curve Plan",
        company_weight_pct=50.00,
        business_unit_weight_pct=30.00,
        individual_weight_pct=20.00,
        discretionary_budget_pct=10.00,
        termination_treatment_policy="STRICT_PAYMENT_DATE",
    )
    scenario.add_target("L3", target_bonus_pct=10.00)
    scenario.add_target("L5", target_bonus_pct=20.00)
    scenario.add_metric(
        "REVENUE", weight_pct=60.00, threshold_value=900, target_value=1000, max_value=1200
    )
    scenario.add_metric(
        "EBITDA", weight_pct=40.00, threshold_value=90, target_value=100, max_value=130
    )
    scenario.add_pool("EAST-A")
    scenario.add_participant(
        "ada",
        "EAST-A",
        employee_code="E001",
        full_name="Ada Long",
        job_level="L5",
        base_salary_cents=20000000,
        hire_date="2025-03-01",
    )
    scenario.add_participant(
        "ben",
        "EAST-A",
        employee_code="E002",
        full_name="Ben Short",
        job_level="L3",
        base_salary_cents=10000000,
        hire_date="2026-07-01",
    )
    # REVENUE lands exactly on its threshold; EBITDA lands mid-band.
    scenario.file_actual("REVENUE", 900, source_note="exactly on threshold")
    scenario.file_actual("EBITDA", 95, source_note="mid band")
    scenario.submit_scorecard("EAST-A", 100.00, scorecard_narrative="at plan")
    scenario.decide_scorecard("EAST-A", "CERTIFY")
    scenario.assign_targets()
    scenario.submit_for_certification()
    return scenario


class TestFiveInputFundingCurve:
    def test_each_metric_scores_on_its_own_band_with_the_threshold_inclusive(
        self, api, plan_admin_headers
    ):
        """PRD §3.4: "The boundaries are inclusive at the bottom of each band: an
        actual exactly equal to `threshold_value` scores exactly 50.00, one exactly
        equal to `target_value` scores exactly 100.00, and one exactly equal to
        `max_value` scores exactly 150.00."

        Design: Difficulty/combinatorial_formula/five_input_funding_curve_lands_on_floor_multiplier
        """
        scenario = _five_input_scenario()
        revenue = validate_success(
            api.get_company_metric(scenario.metrics["REVENUE"]["id"], plan_admin_headers)
        )
        ebitda = validate_success(
            api.get_company_metric(scenario.metrics["EBITDA"]["id"], plan_admin_headers)
        )

        assert_pct(revenue["achievement_pct"], 50.00)
        assert_pct(ebitda["achievement_pct"], 75.00)

    def test_weighted_company_and_capped_unit_scores_blend_to_exactly_eighty(self, api):
        """PRD §3.4: "First, `company_achievement_pct` is the sum, over every company
        metric of the plan in `ACTUAL_ENTERED`, of that metric's `weight_pct` divided
        by 100 and multiplied by its `achievement_pct`; each term is kept at full
        precision and only the total is rounded half up to two decimals."

        Design: Difficulty/combinatorial_formula/five_input_funding_curve_lands_on_floor_multiplier
        """
        scenario = _five_input_scenario()
        plan = scenario.decide_certification(
            "CERTIFY", decision_note="audited actuals accepted"
        )

        assert_pct(plan["company_achievement_pct"], 60.00)
        assert_pct(plan["bu_weighted_achievement_pct"], 100.00)
        assert_pct(plan["blended_achievement_pct"], 80.00)

    def test_blended_eighty_funds_at_the_floor_multiplier_rather_than_at_zero(self, api):
        """PRD §3.4: "The curve is inclusive at the bottom of each band: exactly 80.00
        funds at 0.5000 rather than 0.0000, exactly 100.00 funds at 1.0000, and exactly
        120.00 funds at the 1.5000 cap."

        Design: Difficulty/combinatorial_formula/five_input_funding_curve_lands_on_floor_multiplier
        """
        scenario = _five_input_scenario()
        scenario.decide_certification("CERTIFY", decision_note="audited actuals accepted")
        plan = scenario.fund()

        assert_ratio(plan["funding_multiplier"], 0.5000)
        assert plan["funded_pool_cents"] == 2252055
        assert plan["discretionary_budget_cents"] == 225206
        assert scenario.pools["EAST-A"]["funded_cents"] == 2252055


def _transfer_and_capped_leave_scenario() -> BonusPlanScenario:
    """One participant, a mid-year transfer and a 92-day unpaid leave, filed late."""
    scenario = BonusPlanScenario()
    scenario.add_unit("NORTH", name="North Region")
    scenario.create_plan(
        plan_name="FY26 Rounding Plan",
        company_weight_pct=50.00,
        business_unit_weight_pct=30.00,
        individual_weight_pct=20.00,
        discretionary_budget_pct=10.00,
    )
    scenario.add_target("L3", target_bonus_pct=10.00)
    scenario.add_target("L5", target_bonus_pct=20.00)
    scenario.add_pool("NORTH")
    scenario.add_participant(
        "mia",
        "NORTH",
        employee_code="E100",
        full_name="Mia Mover",
        job_level="L3",
        base_salary_cents=10000000,
        hire_date="2025-06-01",
    )
    # The two events are recorded out of chronological order on purpose.
    scenario.add_transfer(
        "mia", "2026-07-01", "L5", 20000000, "NORTH", note="promotion to L5"
    )
    scenario.add_leave(
        "mia",
        "2026-03-01",
        "2026-05-31",
        paid_leave=False,
        note="unpaid sabbatical, recorded late",
    )
    scenario.assign_targets()
    return scenario


class TestPerSegmentRoundingThenSum:
    def test_transfer_splits_the_window_and_the_leave_cap_clips_sixty_two_days(self, api):
        """PRD §3.3: "Taking that collected set of dates in ascending date order, the
        first 30 dates are credited anyway; every date beyond the thirtieth is excluded
        from proration and the count of excluded dates is written to
        `excluded_leave_days`."

        Design: Difficulty/combinatorial_formula/per_segment_rounding_then_sum_across_transfer_and_capped_leave
        """
        scenario = _transfer_and_capped_leave_scenario()
        award = scenario.refresh_award("mia")

        assert award["segment_count"] == 2
        assert award["excluded_leave_days"] == 62
        assert award["credited_days"] == 303
        assert_pct(award["target_bonus_pct"], 20.00)
        assert award["eligibility_status"] == "ELIGIBLE"

    def test_rounding_each_segment_before_summing_lands_one_cent_lower(self, api):
        """PRD §2.6: "The first is **proration**: a participant's year is cut into
        segments, each with its own salary and job level, and each segment's target is
        rounded to whole cents *before* the segments are summed. Summing un-rounded
        segment amounts and rounding once at the end is explicitly not the rule; the
        two readings can differ by as much as one cent less than the number of
        segments."

        Design: Difficulty/combinatorial_formula/per_segment_rounding_then_sum_across_transfer_and_capped_leave
        """
        scenario = _transfer_and_capped_leave_scenario()
        award = scenario.refresh_award("mia")

        # 326,027 + 2,016,438 per segment; a single rounding would have given 2,342,466.
        assert award["prorated_target_cents"] == 2342465
        assert award["prorated_target_cents"] != 2342466

    def test_pool_and_plan_roll_up_the_already_rounded_segment_sum(self, api):
        """PRD §3.3: "Because the awards changed, each pool immediately recomputes
        `eligible_target_cents` as the sum of `prorated_target_cents` over its awards
        whose `eligibility_status` is anything other than `INELIGIBLE_MIN_SERVICE`, and
        `eligible_headcount` as the count of those same awards, along with
        `max_top_tier_count`, `allocated_cents`, `available_cents` and
        `distribution_status`."

        Design: Difficulty/combinatorial_formula/per_segment_rounding_then_sum_across_transfer_and_capped_leave
        """
        scenario = _transfer_and_capped_leave_scenario()
        pool = scenario.refresh_pool("NORTH")
        plan = scenario.refresh_plan()

        assert pool["eligible_target_cents"] == 2342465
        assert plan["total_target_cents"] == 2342465


def _burden_tier_scenario() -> BonusPlanScenario:
    """A whole-year accrual whose pre-burden cumulative sits just under 5,000,000."""
    scenario = BonusPlanScenario()
    scenario.add_unit("WEST", name="West Region")
    scenario.create_plan(
        plan_name="FY26 Burden Tier Plan",
        company_weight_pct=50.00,
        business_unit_weight_pct=30.00,
        individual_weight_pct=20.00,
        discretionary_budget_pct=10.00,
    )
    scenario.add_target("L5", target_bonus_pct=20.00)
    scenario.add_participant(
        "tia",
        "WEST",
        employee_code="E200",
        full_name="Tia Tier",
        job_level="L5",
        base_salary_cents=24500000,
        hire_date="2024-01-15",
    )
    period = scenario.open_accrual_period("2026-01-01", "2026-12-31", 100.00)
    scenario.post_accrual_period(
        period["id"], posting_note="full-year accrual at forecast target"
    )
    return scenario


class TestBurdenTierEvaluationOrder:
    def test_unprorated_basis_carries_the_cumulative_just_under_the_tier_ceiling(
        self, api
    ):
        """PRD §3.8: "If the plan has no awards yet, `provisional_target_basis` is
        `PARTICIPANT_UNPRORATED` and the basis is the sum, over the plan's participants
        whose `employment_status` is `ACTIVE` or `ON_LEAVE`, of each one's
        `current_base_salary_cents` multiplied by the `target_bonus_pct` of the
        job-level target row for their `current_job_level`, divided by 100 and rounded
        half up to whole cents — whole-year targets, ignoring proration entirely, and
        excluding terminated participants."

        Design: Difficulty/combinatorial_formula/burden_tier_selected_from_pre_burden_cumulative_not_loaded_total
        """
        scenario = _burden_tier_scenario()
        period = scenario.accrual_periods[0]

        assert period["provisional_target_basis"] == "PARTICIPANT_UNPRORATED"
        assert period["provisional_pool_cents"] == 4900000
        assert period["elapsed_days"] == 365
        assert period["cumulative_accrual_target_cents"] == 4900000
        assert period["period_accrual_cents"] == 4900000

    def test_burden_band_is_keyed_on_the_pre_burden_cumulative_not_the_loaded_total(
        self, api
    ):
        """PRD §3.8: "The burden rate is selected from
        `cumulative_accrual_target_cents` — the pre-burden cumulative figure of step
        two, not from the loaded amount and not from the plan's `accrued_total_cents`:
        `burden_rate_pct` is 7.65 when the cumulative figure is below 5,000,000 cents,
        9.25 when it is below 20,000,000 cents, and 10.50 at or above that."

        Design: Difficulty/combinatorial_formula/burden_tier_selected_from_pre_burden_cumulative_not_loaded_total
        """
        scenario = _burden_tier_scenario()
        period = validate_success(
            api.get_accrual_period(scenario.accrual_periods[0]["id"], FC)
        )

        assert_pct(period["burden_rate_pct"], 7.65)
        # 9.25 percent of the same base would have loaded 453,250 cents instead.
        assert period["burden_cents"] == 374850
        assert period["burden_cents"] != 453250
        assert period["total_period_cents"] == 5274850

    def test_plan_ledger_separates_the_base_accrual_from_the_loaded_total(self, api):
        """PRD §3.8: "Posting finally adds `period_accrual_cents` to the plan's
        `accrued_base_cents` and `total_period_cents` to its `accrued_total_cents`."

        Design: Difficulty/combinatorial_formula/burden_tier_selected_from_pre_burden_cumulative_not_loaded_total
        """
        scenario = _burden_tier_scenario()
        plan = scenario.refresh_plan()

        assert plan["accrued_base_cents"] == 4900000
        assert plan["accrued_total_cents"] == 5274850
