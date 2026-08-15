"""Rating forecasts: input-set filtering, improvement pseudo-measure, weighted
projection, and tiered rebate amounts."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_active_measure,
    create_cycle,
    create_draft_set,
    cutpoint_row,
    report_performance,
    setup_four_measure_review_cycle,
    transition_cycle,
    transition_performance,
    validate_error,
    validate_success,
)


class TestForecastCombinatorics:
    def test_forecast_weighted_stars_and_improvement(self, api, stars_analyst_headers):
        """PRD §3.10: "`measures_included` counts the cycle's `ACTIVE` measures
        with a banded star on the chosen basis whose performance is `VALIDATED` or
        `LOCKED`."
        PRD §3.10: "`measures_improved` and `measures_declined` count the eligible
        measures whose basis star is strictly above, respectively strictly below,
        their `prior_cycle_star`."
        PRD §3.10: "`projected_overall_stars` is the weighted mean over the
        included measures plus the improvement pseudo-measure at weight 5 when its
        star is non-null — the sum of each included measure's `weight` times its
        basis star, plus 5 times the improvement star when present, divided by the
        sum of the weights plus 5 when the improvement star is present, snapped to
        the half-star grid (double the quotient, add one half, floor, halve)."

        Draft basis stars are 4/4/3/4 on weights 1/3/4/3; the eligible pair
        improves 1 and declines 0, so the improvement score 0.5 bands to star 5;
        (40 + 25) / (11 + 5) = 4.0625 snaps to 4.0.

        Design: Difficulty/combinatorial_formula/rebate_tiered_projection_multi_input
        """
        sc = setup_four_measure_review_cycle(with_draft_set=True, publish=True,
                                             member_refs=("MBR-A", "MBR-B"))
        resp = api.create_rating_forecast(
            {"rating_cycle_id": sc["cycle"]["id"], "basis": "DRAFT_CUTPOINTS"},
            stars_analyst_headers,
        )
        forecast = validate_success(resp, 201)
        assert forecast["measures_included"] == 4
        assert forecast["measures_eligible"] == 2
        assert forecast["measures_improved"] == 1
        assert forecast["measures_declined"] == 0
        assert forecast["improvement_score"] == pytest.approx(0.5)
        assert forecast["improvement_star"] == 5
        assert forecast["projected_overall_stars"] == pytest.approx(4.0), (
            f"65/16 = 4.0625 must snap to 4.0, got {forecast['projected_overall_stars']}"
        )

    def test_forecast_rebate_tier_and_amount(self, api, stars_analyst_headers):
        """PRD §3.10: "`member_months_used` sums `enrolled_months` over members who
        are `ENROLLED` at forecast time — disenrolled members contribute zero."
        PRD §3.10: "The `rebate_tier_rate` keys off `projected_overall_stars`: 0.0
        when the projection is below 3.5 or null; 0.035 from 3.5 up to but not
        including 4.0; 0.040 from 4.0 up to but not including 4.5; 0.045 from 4.5
        up to but not including 5.0; and 0.050 at exactly 5.0."
        PRD §3.10: "The `projected_rebate_amount` is `member_months_used`
        multiplied by the cycle's `benchmark_pmpm` and by the tier rate, in that
        evaluation order — stars to tier lookup to multiplication to a single final
        rounding — rounded half up to 2 decimal places."

        Projected 4.0 selects the 0.040 tier; 24 member-months x 950.00 x 0.040
        yields 912.00.

        Design: Difficulty/combinatorial_formula/rebate_tiered_projection_multi_input
        """
        sc = setup_four_measure_review_cycle(with_draft_set=True, publish=True,
                                             member_refs=("MBR-A", "MBR-B"))
        resp = api.create_rating_forecast(
            {"rating_cycle_id": sc["cycle"]["id"], "basis": "DRAFT_CUTPOINTS"},
            stars_analyst_headers,
        )
        forecast = validate_success(resp, 201)
        assert forecast["member_months_used"] == 24
        assert forecast["rebate_tier_rate"] == pytest.approx(0.04), (
            f"4.0 stars selects the 0.040 tier, got {forecast['rebate_tier_rate']}"
        )
        assert forecast["projected_rebate_amount"] == pytest.approx(912.00), (
            f"24 x 950.00 x 0.040 = 912.00, got {forecast['projected_rebate_amount']}"
        )


class TestImprovementZeroEligibleEdge:
    def _setup_two_ineligible_measures(self):
        """Cycle in DATA_COLLECTION with two ACTIVE improvement-ineligible
        measures, a DRAFT set, and VALIDATED performances banding to 4 and 2."""
        cycle = create_cycle()
        ma = create_active_measure(cycle["id"], code="BCS",
                                   title="Breast Cancer Screening",
                                   measure_type="PROCESS")
        mb = create_active_measure(cycle["id"], code="COB",
                                   title="Controlling Blood Pressure",
                                   domain="CHRONIC_CARE", measure_type="OUTCOME")
        create_draft_set(cycle["id"],
                         [cutpoint_row(ma["id"], 0.50, 0.60, 0.70, 0.80),
                          cutpoint_row(mb["id"], 0.50, 0.60, 0.70, 0.80)],
                         label="draft-2028")
        transition_cycle(cycle["id"], "DATA_COLLECTION")
        pa = report_performance(cycle["id"], ma["id"], 7, 10)
        pb = report_performance(cycle["id"], mb["id"], 11, 20)
        transition_performance(pa["id"], "VALIDATED")
        transition_performance(pb["id"], "VALIDATED")
        return cycle["id"]

    def test_empty_eligible_set_yields_null_improvement(self, api,
                                                        stars_analyst_headers):
        """PRD §3.9: "When the eligible set is empty, both the `improvement_score`
        and the `improvement_star` are null and the pseudo-measure is **excluded
        entirely** — the weight-5 term does not appear in the weighted average at
        all."

        Design: Difficulty/boundary_precision_check/improvement_empty_eligible_zero_edge
        """
        cycle_id = self._setup_two_ineligible_measures()
        resp = api.create_rating_forecast(
            {"rating_cycle_id": cycle_id, "basis": "DRAFT_CUTPOINTS"},
            stars_analyst_headers,
        )
        forecast = validate_success(resp, 201)
        assert forecast["measures_eligible"] == 0
        assert forecast["improvement_score"] is None
        assert forecast["improvement_star"] is None

    def test_weighted_average_excludes_absent_pseudo_measure(
            self, api, stars_analyst_headers):
        """PRD §3.9: "When the eligible set is empty, both the `improvement_score`
        and the `improvement_star` are null and the pseudo-measure is **excluded
        entirely** — the weight-5 term does not appear in the weighted average at
        all."
        PRD §3.10: "The `rebate_tier_rate` keys off `projected_overall_stars`: 0.0
        when the projection is below 3.5 or null; 0.035 from 3.5 up to but not
        including 4.0; 0.040 from 4.0 up to but not including 4.5; 0.045 from 4.5
        up to but not including 5.0; and 0.050 at exactly 5.0."

        With the weight-5 term absent the average is (1x4 + 3x2) / (1 + 3) = 2.5;
        2.5 is below 3.5 so the tier rate is 0.0 and the projected rebate 0.00.

        Design: Difficulty/boundary_precision_check/improvement_empty_eligible_zero_edge
        """
        cycle_id = self._setup_two_ineligible_measures()
        resp = api.create_rating_forecast(
            {"rating_cycle_id": cycle_id, "basis": "DRAFT_CUTPOINTS"},
            stars_analyst_headers,
        )
        forecast = validate_success(resp, 201)
        assert forecast["projected_overall_stars"] == pytest.approx(2.5), (
            f"Denominator stays 4 with the pseudo-measure absent; got "
            f"{forecast['projected_overall_stars']}"
        )
        assert forecast["rebate_tier_rate"] == pytest.approx(0.0)
        assert forecast["projected_rebate_amount"] == pytest.approx(0.0)


class TestForecastInputFiltering:
    def test_forecast_excludes_reported_performances(self, api, stars_analyst_headers):
        """PRD §2.7: "`RETIRED` measures and `REPORTED` performances never enter
        any weighted or improvement input set."
        PRD §3.10: "`measures_included` counts the cycle's `ACTIVE` measures with
        a banded star on the chosen basis whose performance is `VALIDATED` or
        `LOCKED`."

        The VALIDATED measure bands to 4 (weight 1); the REPORTED measure would
        band to 1 (weight 3) but is excluded, so the projection is exactly 4.0.

        Design: Corner/calculations/forecast_excludes_reported_performances
        """
        cycle = create_cycle()
        ma = create_active_measure(cycle["id"], code="BCS",
                                   title="Breast Cancer Screening",
                                   measure_type="PROCESS")
        mb = create_active_measure(cycle["id"], code="CBP",
                                   title="Controlling Blood Pressure",
                                   domain="CHRONIC_CARE", measure_type="OUTCOME")
        create_draft_set(cycle["id"],
                         [cutpoint_row(ma["id"], 0.50, 0.60, 0.70, 0.80),
                          cutpoint_row(mb["id"], 0.50, 0.60, 0.70, 0.80)],
                         label="draft-2028")
        transition_cycle(cycle["id"], "DATA_COLLECTION")
        pa = report_performance(cycle["id"], ma["id"], 7, 10)
        report_performance(cycle["id"], mb["id"], 1, 20)  # stays REPORTED
        transition_performance(pa["id"], "VALIDATED")

        resp = api.create_rating_forecast(
            {"rating_cycle_id": cycle["id"], "basis": "DRAFT_CUTPOINTS"},
            stars_analyst_headers,
        )
        forecast = validate_success(resp, 201)
        assert forecast["measures_included"] == 1, (
            "The REPORTED performance never enters the forecast input set"
        )
        assert forecast["projected_overall_stars"] == pytest.approx(4.0), (
            "Only the VALIDATED measure's star 4 remains in the average"
        )
        assert forecast["improvement_star"] is None

    def test_forecast_basis_set_availability_errors(self, api, stars_analyst_headers):
        """PRD §3.10: "A forecast on the published basis requires a `PUBLISHED` set
        to exist for the cycle, else `ERR_NO_PUBLISHED_CUTPOINT_SET`; a forecast on
        the draft basis requires at least one `DRAFT` set, else
        `ERR_NO_DRAFT_CUTPOINT_SET`."

        Design: Corner/calculations/forecast_basis_set_availability_errors
        """
        cycle = create_cycle()
        resp = api.create_rating_forecast(
            {"rating_cycle_id": cycle["id"], "basis": "DRAFT_CUTPOINTS"},
            stars_analyst_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NO_DRAFT_CUTPOINT_SET)

        resp = api.create_rating_forecast(
            {"rating_cycle_id": cycle["id"], "basis": "PUBLISHED_CUTPOINTS"},
            stars_analyst_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NO_PUBLISHED_CUTPOINT_SET)
