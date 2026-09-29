"""Two defensible readings of the same money, and the divergence between them."""

import pytest
from test_helpers import (
    FC,
    BonusPlanScenario,
    PAYMENT_DATE_CLOCK,
    assert_pct,
    assert_ratio,
    build_paid_out_scenario,
    validate_success,
)


def _two_participant_accrual_first_scenario() -> BonusPlanScenario:
    """One pool, two participants, an H1 period posted before any award exists."""
    scenario = BonusPlanScenario()
    scenario.add_unit("EAST", name="East Region")
    scenario.create_plan(
        plan_name="FY26 Corporate Bonus",
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
    scenario.add_pool("EAST")
    scenario.add_participant(
        "ada",
        "EAST",
        employee_code="E001",
        full_name="Ada Long",
        job_level="L5",
        base_salary_cents=20000000,
        hire_date="2025-03-01",
    )
    scenario.add_participant(
        "ben",
        "EAST",
        employee_code="E002",
        full_name="Ben Short",
        job_level="L3",
        base_salary_cents=10000000,
        hire_date="2026-07-01",
    )
    # The H1 period is posted while the plan still holds no participant award.
    period = scenario.open_accrual_period("2026-01-01", "2026-06-30", 60.00)
    scenario.post_accrual_period(period["id"], posting_note="H1 provisional accrual")
    scenario.file_actual("REVENUE", 900, source_note="audited FY26 revenue")
    scenario.file_actual("EBITDA", 95, source_note="audited FY26 EBITDA")
    scenario.submit_scorecard("EAST", 100.00, scorecard_narrative="East delivered plan")
    scenario.decide_scorecard("EAST", "CERTIFY", decision_note="scorecard accepted")
    return scenario


class TestProvisionalVersusCertifiedFunding:
    def test_provisional_variant_values_the_pool_off_unprorated_whole_year_targets(
        self, api
    ):
        """PRD §3.8: "If the plan has no awards yet, `provisional_target_basis` is
        `PARTICIPANT_UNPRORATED` and the basis is the sum, over the plan's
        participants whose `employment_status` is `ACTIVE` or `ON_LEAVE`, of each
        one's `current_base_salary_cents` multiplied by the `target_bonus_pct` of
        the job-level target row for their `current_job_level`, divided by 100 and
        rounded half up to whole cents — whole-year targets, ignoring proration
        entirely, and excluding terminated participants."

        Design: Difficulty/dual_variant_calc/provisional_forecast_pool_versus_certified_funded_pool
        """
        scenario = _two_participant_accrual_first_scenario()
        period = validate_success(
            api.get_accrual_period(scenario.accrual_periods[0]["id"], FC)
        )
        assert period["provisional_target_basis"] == "PARTICIPANT_UNPRORATED"
        assert period["provisional_pool_cents"] == 2500000
        assert period["elapsed_days"] == 181
        assert period["cumulative_accrual_target_cents"] == 1239726
        assert period["total_period_cents"] == 1334565

    def test_certified_variant_values_the_same_company_result_off_prorated_awards(
        self, api, committee_headers
    ):
        """PRD §2.6: "each business unit's pool is rounded to whole cents separately,
        and the plan's authoritative `funded_pool_cents` is the sum of those
        already-rounded per-pool figures."

        Design: Difficulty/dual_variant_calc/provisional_forecast_pool_versus_certified_funded_pool
        """
        scenario = _two_participant_accrual_first_scenario()
        scenario.assign_targets()
        scenario.submit_for_certification()
        scenario.decide_certification("CERTIFY", decision_note="metrics certified")
        plan = validate_success(api.fund_pool(scenario.plan_id, committee_headers))

        assert_pct(plan["company_achievement_pct"], 60.00)
        assert_pct(plan["blended_achievement_pct"], 80.00)
        assert_ratio(plan["funding_multiplier"], 0.5000)
        assert plan["total_target_cents"] == 4504110
        assert plan["funded_pool_cents"] == 2252055

        pool = scenario.refresh_pool("EAST")
        assert pool["funded_cents"] == 2252055
        assert pool["min_utilization_cents"] == 2240794

    def test_divergence_between_the_two_variants_is_the_input_set_not_the_curve(
        self, api
    ):
        """PRD §3.8: "Posting first values the pool under the **provisional funding
        variant**, which differs from the certified variant in three ways: the
        company component comes from the period's own
        `forecast_company_achievement_pct` rather than from audited actuals, the
        business-unit component defaults to full target achievement until scorecards
        are certified, and the target basis may be un-prorated."

        Design: Difficulty/dual_variant_calc/provisional_forecast_pool_versus_certified_funded_pool
        """
        scenario = _two_participant_accrual_first_scenario()
        provisional = scenario.accrual_periods[0]["provisional_pool_cents"]
        scenario.assign_targets()
        scenario.submit_for_certification()
        scenario.decide_certification("CERTIFY")
        plan = scenario.fund()

        # Both readings were fed the identical 60.00 company achievement.
        assert_pct(plan["company_achievement_pct"], 60.00)
        assert provisional == 2500000
        assert plan["funded_pool_cents"] == 2252055
        assert provisional - plan["funded_pool_cents"] == 247945


def _retiree_scenario(policy: str) -> BonusPlanScenario:
    """A single L5 retiree, paid out under the named termination-treatment policy."""

    def retire(scenario: BonusPlanScenario):
        scenario.add_termination("rita", "2026-09-30", "RETIREMENT", note="retired end of September")

    return build_paid_out_scenario(
        payment_clock=PAYMENT_DATE_CLOCK,
        plan_overrides={
            "plan_name": f"FY26 {policy} Policy",
            "termination_treatment_policy": policy,
        },
        participants=(
            {
                "label": "rita",
                "employee_code": "E001",
                "full_name": "Rita Retire",
                "job_level": "L5",
                "base_salary_cents": 20000000,
                "hire_date": "2025-03-01",
            },
        ),
        hook=retire,
    )


class TestTerminationTreatmentPolicyVariants:
    @pytest.mark.parametrize(
        "policy,expected_payment_status,expected_payout_cents",
        [
            ("STRICT_PAYMENT_DATE", "FORFEITED", 0),
            ("GOOD_LEAVER_PRORATION", "PAID", 2991781),
        ],
    )
    def test_same_retiree_pays_or_forfeits_purely_on_the_declared_policy(
        self, api, policy, expected_payment_status, expected_payout_cents
    ):
        """PRD §3.9: "Under `STRICT_PAYMENT_DATE`, an award pays its
        `final_award_cents` if the participant was employed on the payment date and
        pays 0 otherwise: any termination before the payment date forfeits the whole
        award regardless of reason, and the retiree and the resigner are treated
        identically. Under `GOOD_LEAVER_PRORATION`, an award pays its
        `final_award_cents` if the participant was employed on the payment date, and
        also pays the full already-prorated `final_award_cents` if the participant's
        `eligibility_status` is `GOOD_LEAVER`; only a `BAD_LEAVER` forfeits."

        Design: Difficulty/dual_variant_calc/strict_payment_date_versus_good_leaver_payout_of_same_retiree
        """
        scenario = _retiree_scenario(policy)
        award = scenario.refresh_award("rita")

        assert award["eligibility_status"] == "GOOD_LEAVER"
        assert award["credited_days"] == 273
        assert award["prorated_target_cents"] == 2991781
        assert award["payment_status"] == expected_payment_status
        assert award["payout_amount_cents"] == expected_payout_cents

    def test_run_totals_split_the_same_award_between_paid_and_forfeited(self, api):
        """PRD §3.9: "From the per-award verdicts the plan's `paid_total_cents` (the
        sum of `payout_amount_cents` over awards in `PAID`) and
        `forfeited_total_cents` (the sum of `final_award_cents` over awards in
        `FORFEITED`) are written."

        Design: Difficulty/dual_variant_calc/strict_payment_date_versus_good_leaver_payout_of_same_retiree
        """
        strict = _retiree_scenario("STRICT_PAYMENT_DATE")
        good_leaver = _retiree_scenario("GOOD_LEAVER_PRORATION")

        assert strict.payout_run["total_forfeited_cents"] == 2991781
        assert strict.payout_run["total_paid_cents"] == 0
        assert good_leaver.payout_run["total_paid_cents"] == 2991781
        assert good_leaver.payout_run["total_forfeited_cents"] == 0

        strict_plan = strict.refresh_plan()
        good_leaver_plan = good_leaver.refresh_plan()
        assert (
            good_leaver_plan["paid_total_cents"] - strict_plan["paid_total_cents"]
            == 2991781
        )
