"""Single-unit boundaries: the curve floor, the service gate, the utilisation cent."""

from test_helpers import (
    ApiErrorId,
    BonusPlanScenario,
    assert_pct,
    assert_ratio,
    validate_error,
)


def _curve_scenario(plan_name: str, revenue_actual, source_note: str) -> BonusPlanScenario:
    """One L5 award of 4,000,000, certified off a single 100.00-weighted metric."""
    scenario = BonusPlanScenario()
    scenario.add_unit("UNIT-B1", name="Unit B1")
    scenario.create_plan(plan_name=plan_name, discretionary_budget_pct=10.00)
    scenario.add_target("L5", target_bonus_pct=20.00)
    scenario.add_metric(
        "REVENUE", weight_pct=100.00, threshold_value=900, target_value=1000, max_value=1200
    )
    scenario.add_pool("UNIT-B1")
    scenario.add_participant(
        "ada",
        "UNIT-B1",
        employee_code="E001",
        full_name="Ada Long",
        job_level="L5",
        base_salary_cents=20000000,
        hire_date="2025-03-01",
    )
    scenario.file_actual("REVENUE", revenue_actual, source_note=source_note)
    scenario.submit_scorecard("UNIT-B1", 100.00, scorecard_narrative="at plan")
    scenario.decide_scorecard("UNIT-B1", "CERTIFY")
    scenario.assign_targets()
    scenario.submit_for_certification()
    scenario.decide_certification("CERTIFY", decision_note="audited actual accepted")
    return scenario


class TestFundingCurveFloorBoundary:
    def test_one_hundredth_of_a_point_below_the_floor_yields_a_zero_multiplier(self, api):
        """PRD §3.4: "Fourth, the blended figure is pushed through the **funding curve**
        to produce `funding_multiplier`, rounded half up to four decimals: a blended
        achievement below 80.00 yields 0.0000; from 80.00 up to but not including 100.00
        the multiplier is 0.50 plus the difference between the blended figure and 80,
        divided by 20, multiplied by 0.50; from 100.00 up to but not including 120.00 it
        is 1.00 plus the difference between the blended figure and 100, divided by 20,
        multiplied by 0.50; and at 120.00 or above it is the 1.5000 cap."

        Design: Difficulty/boundary_precision_check/funding_curve_floor_at_blended_eighty_versus_seventy_nine_point_nine_nine
        """
        scenario = _curve_scenario(
            "FY26 Below Floor", 919.96, "one hundredth of a point below"
        )

        assert_pct(scenario.metrics["REVENUE"]["achievement_pct"], 59.98)
        assert_pct(scenario.plan["company_achievement_pct"], 59.98)
        assert_pct(scenario.plan["blended_achievement_pct"], 79.99)
        assert_ratio(scenario.plan["funding_multiplier"], 0.0000)

    def test_the_zero_multiplier_refuses_to_open_allocation_and_mints_no_money(
        self, api, committee_headers
    ):
        """PRD §3.4: "It requires a `funding_multiplier` strictly greater than 0.0000 — a
        plan whose blended achievement missed the 80.00 floor cannot open allocation at
        all, and the attempt is refused with `ERR_FUNDING_MULTIPLIER_ZERO`."

        Design: Difficulty/boundary_precision_check/funding_curve_floor_at_blended_eighty_versus_seventy_nine_point_nine_nine
        """
        scenario = _curve_scenario(
            "FY26 Below Floor", 919.96, "one hundredth of a point below"
        )

        response = api.fund_pool(scenario.plan_id, committee_headers)
        validate_error(
            response, ApiErrorId.ERR_FUNDING_MULTIPLIER_ZERO.value, expected_status=409
        )

        plan = scenario.refresh_plan()
        assert plan["status"] == "CERTIFIED"
        assert plan["funded_pool_cents"] == 0
        assert plan["discretionary_budget_cents"] == 0

        pool = scenario.refresh_pool("UNIT-B1")
        assert pool["calibration_status"] == "SCORECARD_CERTIFIED"
        assert pool["funded_cents"] == 0

    def test_landing_exactly_on_the_floor_funds_at_half_and_not_at_nothing(self, api):
        """PRD §3.4: "The curve is inclusive at the bottom of each band: exactly 80.00
        funds at 0.5000 rather than 0.0000, exactly 100.00 funds at 1.0000, and exactly
        120.00 funds at the 1.5000 cap."

        Design: Difficulty/boundary_precision_check/funding_curve_floor_at_blended_eighty_versus_seventy_nine_point_nine_nine
        """
        scenario = _curve_scenario("FY26 On Floor", 920, "exactly on the floor")

        assert_pct(scenario.metrics["REVENUE"]["achievement_pct"], 60.00)
        assert_pct(scenario.plan["blended_achievement_pct"], 80.00)
        assert_ratio(scenario.plan["funding_multiplier"], 0.5000)

        plan = scenario.fund()
        assert plan["status"] == "ALLOCATION_OPEN"
        assert plan["funded_pool_cents"] == 2000000
        assert plan["discretionary_budget_cents"] == 200000

        pool = scenario.pools["UNIT-B1"]
        assert pool["funded_cents"] == 2000000
        assert pool["min_utilization_cents"] == 1990000


def _min_service_scenario() -> BonusPlanScenario:
    """Two late hires one calendar day apart, straddling the ninety-day gate."""
    scenario = BonusPlanScenario()
    scenario.add_unit("UNIT-B2", name="Unit B2")
    scenario.create_plan(plan_name="FY26 Min Service Plan", discretionary_budget_pct=10.00)
    scenario.add_target("L3", target_bonus_pct=10.00)
    scenario.add_pool("UNIT-B2")
    scenario.add_participant(
        "nia",
        "UNIT-B2",
        employee_code="E090",
        full_name="Nia Ninety",
        job_level="L3",
        base_salary_cents=10000000,
        hire_date="2026-10-03",
    )
    scenario.add_participant(
        "oli",
        "UNIT-B2",
        employee_code="E089",
        full_name="Oli Eightynine",
        job_level="L3",
        base_salary_cents=10000000,
        hire_date="2026-10-04",
    )
    scenario.assign_targets()
    return scenario


class TestMinimumServiceDayBoundary:
    def test_exactly_ninety_credited_days_is_eligible_and_eighty_nine_is_not(self, api):
        """PRD §3.3: "A participant credited with fewer than 90 days is
        `INELIGIBLE_MIN_SERVICE`, and their `prorated_target_cents` is forced to 0;
        exactly 90 credited days is eligible, and 89 is not."

        Design: Difficulty/boundary_precision_check/minimum_service_at_exactly_ninety_credited_days
        """
        scenario = _min_service_scenario()

        ninety = scenario.refresh_award("nia")
        assert ninety["credited_days"] == 90
        assert ninety["eligibility_status"] == "ELIGIBLE"
        assert ninety["prorated_target_cents"] == 246575

        eighty_nine = scenario.refresh_award("oli")
        assert eighty_nine["credited_days"] == 89
        assert eighty_nine["eligibility_status"] == "INELIGIBLE_MIN_SERVICE"
        assert eighty_nine["prorated_target_cents"] == 0

    def test_the_award_below_the_gate_leaves_the_pool_and_plan_roll_ups(self, api):
        """PRD §3.3: "Because the awards changed, each pool immediately recomputes
        `eligible_target_cents` as the sum of `prorated_target_cents` over its awards
        whose `eligibility_status` is anything other than `INELIGIBLE_MIN_SERVICE`, and
        `eligible_headcount` as the count of those same awards, along with
        `max_top_tier_count`, `allocated_cents`, `available_cents` and
        `distribution_status`. The plan's `total_target_cents` is then the sum of
        `eligible_target_cents` across the pools of the plan."

        Design: Difficulty/boundary_precision_check/minimum_service_at_exactly_ninety_credited_days
        """
        scenario = _min_service_scenario()

        pool = scenario.refresh_pool("UNIT-B2")
        assert pool["eligible_target_cents"] == 246575
        assert pool["eligible_headcount"] == 1
        assert pool["max_top_tier_count"] == 1

        assert scenario.refresh_plan()["total_target_cents"] == 246575


def _utilization_scenario() -> BonusPlanScenario:
    """A 3,000,000 pool allocated to 2,984,999 — one cent under its floor."""
    scenario = BonusPlanScenario()
    scenario.add_unit("UNIT-B3", name="Unit B3")
    scenario.create_plan(plan_name="FY26 Utilization Plan", discretionary_budget_pct=10.00)
    scenario.add_target("L3", target_bonus_pct=10.00)
    scenario.add_metric(
        "REVENUE", weight_pct=100.00, threshold_value=900, target_value=1000, max_value=1200
    )
    scenario.add_pool("UNIT-B3")
    for label, employee_code, full_name in (
        ("ann", "E301", "Ann Top"),
        ("bob", "E302", "Bob Mid"),
        ("cal", "E303", "Cal Zero"),
    ):
        scenario.add_participant(
            label,
            "UNIT-B3",
            employee_code=employee_code,
            full_name=full_name,
            job_level="L3",
            base_salary_cents=10000000,
            hire_date="2025-01-01",
        )
    scenario.file_actual("REVENUE", 1000, source_note="at target")
    scenario.submit_scorecard("UNIT-B3", 100.00, scorecard_narrative="at plan")
    scenario.decide_scorecard("UNIT-B3", "CERTIFY")
    scenario.assign_targets()
    scenario.submit_for_certification()
    scenario.decide_certification("CERTIFY", decision_note="at target")
    scenario.fund()
    scenario.propose("ann", 1500000, allocation_rationale="top performer at 1.5x")
    scenario.propose("bob", 1484999, allocation_rationale="strong contributor")
    scenario.propose("cal", 0, allocation_rationale="no award this cycle")
    return scenario


class TestUnderUtilizationFloorCent:
    def test_one_cent_under_the_floor_is_under_utilized_and_refuses_the_submission(
        self, api
    ):
        """PRD §3.7: "The pool's `distribution_status` must be `WITHIN_GUIDELINES` or
        `NO_ELIGIBLE_PARTICIPANTS` — an `UNDER_UTILIZED` pool that has left money on the
        table and an `OVER_ALLOCATED` pool that has overspent are both refused with
        `ERR_POOL_NOT_WITHIN_GUIDELINES`."

        Design: Difficulty/boundary_precision_check/under_utilization_floor_cent_at_calibration_submission
        """
        scenario = _utilization_scenario()
        pool = scenario.refresh_pool("UNIT-B3")
        assert pool["funded_cents"] == 3000000
        assert pool["min_utilization_cents"] == 2985000
        assert pool["allocated_cents"] == 2984999
        assert pool["distribution_status"] == "UNDER_UTILIZED"

        response = api.submit_calibration(
            scenario.pool_id("UNIT-B3"),
            scenario.manager_headers("UNIT-B3"),
            {"scorecard_narrative": "first attempt, one cent short"},
        )
        validate_error(
            response, ApiErrorId.ERR_POOL_NOT_WITHIN_GUIDELINES.value, expected_status=422
        )
        assert scenario.refresh_pool("UNIT-B3")["calibration_status"] == "ALLOCATING"

    def test_allocating_exactly_the_floor_cent_is_within_guidelines_and_submits(
        self, api
    ):
        """PRD §3.5: "Finally the pool's `distribution_status` is decided in this order:
        `NO_ELIGIBLE_PARTICIPANTS` when `eligible_headcount` is 0; otherwise
        `OVER_ALLOCATED` when `allocated_cents` is strictly greater than `funded_cents`;
        otherwise `UNDER_UTILIZED` when `allocated_cents` is strictly less than
        `min_utilization_cents`; otherwise `WITHIN_GUIDELINES`. Allocating exactly
        `min_utilization_cents` is therefore within guidelines, since the
        under-utilization test is strict."

        Design: Difficulty/boundary_precision_check/under_utilization_floor_cent_at_calibration_submission
        """
        scenario = _utilization_scenario()
        scenario.propose("bob", 1485000, allocation_rationale="revised up by one cent")

        pool = scenario.refresh_pool("UNIT-B3")
        assert pool["allocated_cents"] == 2985000
        assert pool["available_cents"] == 15000
        assert pool["distribution_status"] == "WITHIN_GUIDELINES"
        assert pool["top_tier_award_count"] == 1

        submitted = scenario.submit_calibration(
            "UNIT-B3", scorecard_narrative="second attempt, exactly on the floor"
        )
        assert submitted["calibration_status"] == "CALIBRATION_SUBMITTED"

        plan = scenario.refresh_plan()
        assert plan["under_utilized_pool_count"] == 0
        assert plan["governance_posture"] == "COMPLIANT"

    def test_both_sides_of_the_floor_display_the_very_same_utilisation_percent(self, api):
        """PRD §3.5: "`utilization_pct` is `allocated_cents` multiplied by 10000, divided
        by `funded_cents`, rounded half up to a whole number and then divided by 100, and
        is 0.00 when `funded_cents` is 0."

        Design: Difficulty/boundary_precision_check/under_utilization_floor_cent_at_calibration_submission
        """
        scenario = _utilization_scenario()
        short = scenario.refresh_pool("UNIT-B3")
        assert_pct(short["utilization_pct"], 99.50)
        assert short["distribution_status"] == "UNDER_UTILIZED"

        scenario.propose("bob", 1485000, allocation_rationale="revised up by one cent")
        exact = scenario.refresh_pool("UNIT-B3")
        assert_pct(exact["utilization_pct"], 99.50)
        assert exact["distribution_status"] == "WITHIN_GUIDELINES"

        # The four-decimal ratios are what separate the two proposals.
        assert_ratio(scenario.refresh_award("ann")["allocation_ratio"], 1.5000)
        assert_ratio(scenario.refresh_award("bob")["allocation_ratio"], 1.4850)
        assert_ratio(scenario.refresh_award("cal")["allocation_ratio"], 0.0000)
