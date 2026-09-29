"""Dual-variant readings: the exposure projection and the compensation variants.

Both cases return two figures from one set of inputs, where the figures differ
only in a single pinned dimension — where the day count stops for the
projection, and which compensation base feeds the price component for a
disclosure.
"""

from __future__ import annotations

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    ApiClient,
    DISCLOSURE_REASONABLE,
    DISCLOSURE_UNREASONABLE,
    POSTURE_AT_RISK,
    POSTURE_DEFICIENT,
    VARIANT_DIRECT_ONLY,
    VARIANT_TOTAL_WITH_INDIRECT,
    assert_penalty_projection,
    assert_score_close,
    assert_unreasonableness_is_sum_of_components,
    fixtures as fx,
    validate_success,
)


class TestPenaltyProjectionVariants:
    """The projection returns both an accrued and a statutory figure at once."""

    def test_projection_reports_both_variants_for_one_open_gag_deficiency(
        self, api: ApiClient
    ) -> None:
        """Both day counts run from the same onset and stop in different places.

        PRD 3.9: "For a plan year with 6,000 covered lives — multiplier 2.0 — an
        `end_date` of 2027-12-31, and a single gag-clause deficiency whose onset
        is 2027-07-10, a projection as of 2027-07-20 reports
        `accrued_to_date_cents` of 330,000, being 15,000 cents times 11 days
        times 2.0, and `statutory_maximum_cents` of 5,250,000, being 15,000
        cents times 175 days times 2.0."

        Design: Difficulty/dual_variant_calc/penalty_projection_accrued_vs_statutory_maximum
        """
        fx.set_clock(api, "2027-07-10T09:00:00Z")
        setup = fx.plan_year_with_gag_accrual(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]

        fx.set_clock(api, "2027-07-20T09:00:00Z")
        response = api.get_penalty_projection(
            plan_year_id,
            COMPLIANCE_OFFICER_HEADERS,
            params={"as_of_date": "2027-07-20"},
        )
        projection = validate_success(response)

        assert_penalty_projection(projection)
        assert projection["accrued_to_date_cents"] == 330_000
        assert projection["statutory_maximum_cents"] == 5_250_000
        assert projection["open_deficiency_count"] == 1
        assert projection["size_multiplier"] == 2.0

    def test_projection_deliberately_disagrees_with_posted_exposure(
        self, api: ApiClient
    ) -> None:
        """Eleven projected days sit beside a single posted one-day accrual.

        PRD 3.9: "The projection deliberately disagrees with
        `penalty_exposure_cents`, and that disagreement is the feature: a
        deficiency open for eleven days projects eleven days of exposure while
        the ledger still holds only the single one-day accrual posted when it
        opened."

        Design: Difficulty/dual_variant_calc/penalty_projection_accrued_vs_statutory_maximum
        """
        fx.set_clock(api, "2027-07-10T09:00:00Z")
        setup = fx.plan_year_with_gag_accrual(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]

        fx.set_clock(api, "2027-07-20T09:00:00Z")
        projection = fx.read_penalty_projection(
            api, plan_year_id, as_of_date="2027-07-20"
        )
        plan_year = fx.read_plan_year(api, plan_year_id)

        assert plan_year["penalty_exposure_cents"] == 30_000
        assert projection["accrued_to_date_cents"] == 330_000
        assert projection["accrued_to_date_cents"] != plan_year["penalty_exposure_cents"]
        assert plan_year["deficiency_points"] == 6
        assert plan_year["compliance_posture"] == POSTURE_DEFICIENT

    def test_projection_day_counts_are_inclusive_of_both_endpoints(
        self, api: ApiClient
    ) -> None:
        """A deficiency priced on its own onset day still counts one whole day.

        PRD 3.9: "For each open deficiency the day count is inclusive of both
        endpoints, exactly as in accrual pricing."

        Design: Difficulty/dual_variant_calc/penalty_projection_accrued_vs_statutory_maximum
        """
        fx.set_clock(api, "2027-07-10T09:00:00Z")
        setup = fx.plan_year_with_gag_accrual(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]

        projection = fx.read_penalty_projection(
            api, plan_year_id, as_of_date="2027-07-10"
        )

        # Onset and as_of_date coincide, so the accrued variant covers one day.
        assert projection["accrued_to_date_cents"] == 15_000 * 1 * 2
        assert projection["statutory_maximum_cents"] == 15_000 * 175 * 2
        assert projection["open_deficiency_count"] == 1


class TestCompensationVariantBranch:
    """The parent contract's type decides which compensation base is scored."""

    def test_broker_variant_scores_all_in_remuneration_as_unreasonable(
        self, api: ApiClient
    ) -> None:
        """A broker is judged on direct plus indirect compensation.

        PRD 3.7: "a broker with 1,000,000 cents direct, 400,000 cents indirect,
        a benchmark of 1,000,000 cents, a scope score of 5 and a completeness
        score of 4 has a base of 1,400,000 cents, a ratio of 1.4, components of
        56.00, 0.00 and 11.67, and a score of 67.67 — `UNREASONABLE`."

        Design: Difficulty/dual_variant_calc/compensation_variant_broker_total_vs_consultant_direct
        """
        fx.set_clock(api, "2027-05-01T09:00:00Z")
        setup = fx.activated_plan_year_with_roster(api, covered_lives=6000)

        assessed = fx.assessed_compensation_disclosure(
            api,
            setup["broker_contract"]["id"],
            direct_comp_cents=1_000_000,
            indirect_comp_cents=400_000,
            benchmark_median_cents=1_000_000,
            services_scope_score=5,
            disclosure_completeness_score=4,
        )

        assert assessed["variant_applied"] == VARIANT_TOTAL_WITH_INDIRECT
        assert_score_close(assessed["component_price_score"], 56.00)
        assert_score_close(assessed["component_scope_score"], 0.00)
        assert_score_close(assessed["component_disclosure_score"], 11.67)
        assert_score_close(assessed["unreasonableness_score"], 67.67)
        assert assessed["status"] == DISCLOSURE_UNREASONABLE
        assert_unreasonableness_is_sum_of_components(assessed)

    def test_consultant_variant_excludes_indirect_and_lands_reasonable(
        self, api: ApiClient
    ) -> None:
        """A consultant is judged on direct compensation alone.

        PRD 3.7: "A consultant with identical inputs has a base of 1,000,000
        cents, a ratio of 1.0, components of 40.00, 0.00 and 11.67, and a score
        of 51.67 — `REASONABLE`."

        Design: Difficulty/dual_variant_calc/compensation_variant_broker_total_vs_consultant_direct
        """
        fx.set_clock(api, "2027-05-01T09:00:00Z")
        setup = fx.activated_plan_year_with_roster(api, covered_lives=6000)

        assessed = fx.assessed_compensation_disclosure(
            api,
            setup["consultant_contract"]["id"],
            direct_comp_cents=1_000_000,
            indirect_comp_cents=400_000,
            benchmark_median_cents=1_000_000,
            services_scope_score=5,
            disclosure_completeness_score=4,
        )

        assert assessed["variant_applied"] == VARIANT_DIRECT_ONLY
        assert_score_close(assessed["component_price_score"], 40.00)
        assert_score_close(assessed["component_scope_score"], 0.00)
        assert_score_close(assessed["component_disclosure_score"], 11.67)
        assert_score_close(assessed["unreasonableness_score"], 51.67)
        assert assessed["status"] == DISCLOSURE_REASONABLE
        # The indirect figure is still disclosed and still stored.
        assert assessed["indirect_comp_cents"] == 400_000

    def test_only_the_unreasonable_branch_moves_the_plan_year(
        self, api: ApiClient
    ) -> None:
        """Two identical disclosures, one plan-year consequence between them.

        PRD 3.7: "Where they diverge is the plan year: the `UNREASONABLE` branch
        recomputes the plan year's `deficiency_points`, adding three points for
        this disclosure, and recomputes `compliance_posture` — while the
        `REASONABLE` branch touches no plan year field at all."

        Design: Difficulty/dual_variant_calc/compensation_variant_broker_total_vs_consultant_direct
        """
        fx.set_clock(api, "2027-05-01T09:00:00Z")
        setup = fx.activated_plan_year_with_roster(api, covered_lives=6000)
        plan_year_id = setup["plan_year"]["id"]

        inputs = {
            "direct_comp_cents": 1_000_000,
            "indirect_comp_cents": 400_000,
            "benchmark_median_cents": 1_000_000,
            "services_scope_score": 5,
            "disclosure_completeness_score": 4,
        }
        fx.assessed_compensation_disclosure(
            api, setup["broker_contract"]["id"], **inputs
        )
        after_unreasonable = fx.read_plan_year(api, plan_year_id)

        fx.assessed_compensation_disclosure(
            api, setup["consultant_contract"]["id"], **inputs
        )
        after_reasonable = fx.read_plan_year(api, plan_year_id)

        assert after_unreasonable["deficiency_points"] == 3
        assert after_unreasonable["compliance_posture"] == POSTURE_AT_RISK
        # The reasonable branch adds nothing at all.
        assert after_reasonable["deficiency_points"] == 3
        assert after_reasonable["compliance_posture"] == POSTURE_AT_RISK
        assert after_reasonable["penalty_exposure_cents"] == 0
