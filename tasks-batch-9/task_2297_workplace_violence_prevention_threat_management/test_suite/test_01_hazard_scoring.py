"""Hazard scoring: the two score variants and the clamp pair that bounds them."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    ApiClient,
    add_hazard_assessment,
    assert_hazard_assessment,
    assert_plan_metrics,
    assert_two_decimal_value,
    build_hazard_validation,
    read_plan,
    setup_draft_plan,
    setup_programme,
    setup_screened_plan,
    setup_work_area,
)


class TestScreeningAndValidatedVariants:
    """The same assessment row scored before and after a site walkthrough."""

    def test_screening_variant_scores_the_six_terms_without_mitigation_credit(
        self, api: ApiClient
    ) -> None:
        """A front-desk screening of four incidents at high proximity scores 64.00 as TIER_1_ENGINEERING.

        PRD: "Under the `SCREENING` variant the `hazard_score` is the base rounded half-up to two decimal places, `score_variant` is recorded as `SCREENING`, and `mitigation_verified` is forced false — mitigation claims are not trusted until somebody has walked the area."
        Design: Difficulty/dual_variant_calc/hazard_score_screening_versus_validated_credit_delta
        """
        ctx = setup_screened_plan(api)
        assessment = ctx["hazard_assessment"]

        assert_hazard_assessment(
            assessment,
            hazard_score=64.00,
            control_tier="TIER_1_ENGINEERING",
            score_variant="SCREENING",
            status="SCREENING",
            mitigation_verified=False,
        )
        assert assessment["authored_by_employee_id"] == ctx["so"]["id"]
        assert assessment["validated_by_employee_id"] is None
        assert assessment["walkthrough_note"] is None
        assert assessment["mitigation_credits"] == 0
        assert assessment["barrier_installed"] is False
        assert_plan_metrics(read_plan(api, ctx), unmitigated_hazard_count=1)

    def test_validated_variant_subtracts_a_twenty_five_point_mitigation_credit(
        self, api: ApiClient
    ) -> None:
        """Three credited controls plus a barrier take the same base from 64.00 down to 39.00.

        PRD: "The credit is `mitigation_credits`, capped at 4, multiplied by 5 points each, plus a further 10 points when `barrier_installed` is true — so the maximum achievable credit is 30 points, and a claim of six credits earns the same 20 points as a claim of four."
        Design: Difficulty/dual_variant_calc/hazard_score_screening_versus_validated_credit_delta
        """
        ctx = setup_screened_plan(api)
        screening_score = ctx["hazard_assessment"]["hazard_score"]

        validated = get_success_data(
            api.validate_hazard_assessment(
                ctx["hazard_assessment"]["id"],
                build_hazard_validation(
                    walkthrough_note=(
                        "Badge reader, mirrored counter and panic strip verified on site."
                    ),
                    mitigation_credits=3,
                    barrier_installed=True,
                ),
                ctx["headers"]["site_manager"],
            )
        )

        assert_hazard_assessment(
            validated,
            hazard_score=39.00,
            control_tier="TIER_2_ADMINISTRATIVE",
            score_variant="VALIDATED",
            status="VALIDATED",
            mitigation_verified=True,
        )
        assert validated["validated_by_employee_id"] == ctx["sm"]["id"]
        assert_two_decimal_value(
            screening_score - validated["hazard_score"], 25.00, "variant delta"
        )
        assert_plan_metrics(read_plan(api, ctx), unmitigated_hazard_count=0)


class TestClampOrderOnTheRawTermSum:
    """The lone-worker floor runs before the 100-point cap, and the cash term is capped first."""

    def _three_area_worksite(self, api: ApiClient):
        """The standard front desk plus a lone-worker yard and a cash vault, and a DRAFT plan."""
        ctx = setup_programme(api)
        ctx["lone_area"] = setup_work_area(
            api,
            ctx["worksite"]["id"],
            name="Night Yard",
            job_function="FIELD_SERVICE",
            public_access_flag=False,
            lone_worker_flag=True,
            night_shift_flag=False,
            occupancy_cap=4,
        )
        ctx["vault_area"] = setup_work_area(
            api,
            ctx["worksite"]["id"],
            name="Cash Vault",
            job_function="CASH_HANDLING",
            public_access_flag=True,
            lone_worker_flag=False,
            night_shift_flag=True,
            occupancy_cap=4,
        )
        return setup_draft_plan(api, ctx)

    def test_lone_worker_floor_lifts_a_benign_area_out_of_the_lowest_tier(
        self, api: ApiClient
    ) -> None:
        """A raw term sum of 8 on a lone-worker area is replaced by 45.00 and tiers TIER_2_ADMINISTRATIVE.

        PRD: "If the area's `lone_worker_flag` is true, the raw total is replaced by whichever is larger, itself or 45 points — a lone-worker area can never score below 45 no matter how benign its other inputs, which is often enough on its own to lift the area out of the lowest control tier."
        Design: Difficulty/combinatorial_formula/hazard_score_lone_worker_floor_applied_before_cap
        """
        ctx = self._three_area_worksite(api)

        assessment = add_hazard_assessment(
            api,
            ctx,
            ctx["lone_area"]["id"],
            reported_incident_count=0,
            proximity_factor="MODERATE",
            cash_on_hand_cents=0,
            min_staff_per_shift=3,
        )

        assert_hazard_assessment(
            assessment, hazard_score=45.00, control_tier="TIER_2_ADMINISTRATIVE"
        )
        assert assessment["control_tier"] != "TIER_3_TRAINING_ONLY"
        assert_plan_metrics(read_plan(api, ctx), hazard_coverage_pct=33.33)

    def test_hundred_point_cap_clamps_a_raw_sum_of_one_hundred_and_ten(
        self, api: ApiClient
    ) -> None:
        """A cash vault whose six terms total 110 scores exactly 100.00, its cash term already capped at 20.

        PRD: "The result is then replaced by whichever is smaller, itself or 100 points."
        Design: Difficulty/combinatorial_formula/hazard_score_lone_worker_floor_applied_before_cap
        """
        ctx = self._three_area_worksite(api)
        add_hazard_assessment(
            api,
            ctx,
            ctx["lone_area"]["id"],
            reported_incident_count=0,
            proximity_factor="MODERATE",
            cash_on_hand_cents=0,
            min_staff_per_shift=3,
        )

        assessment = add_hazard_assessment(
            api,
            ctx,
            ctx["vault_area"]["id"],
            reported_incident_count=8,
            proximity_factor="HIGH",
            cash_on_hand_cents=30000000,
            min_staff_per_shift=1,
        )

        assert_hazard_assessment(
            assessment,
            hazard_score=100.00,
            control_tier="TIER_1_ENGINEERING",
            mitigation_verified=False,
        )
        assert_plan_metrics(
            read_plan(api, ctx), hazard_coverage_pct=66.67, unmitigated_hazard_count=1
        )
