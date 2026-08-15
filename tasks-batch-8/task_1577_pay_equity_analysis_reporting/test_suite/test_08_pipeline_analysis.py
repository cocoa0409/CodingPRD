"""Hiring/promotion pipeline analysis: pass rates, adverse impact (PRD §3.6)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_pipeline_analysis_payload,
    create_study,
    validate_error,
    validate_success,
)

_ANALYST = TEST_USERS["comp_analyst_headers"]


def _analyst():
    return _ANALYST


class TestAdverseImpactNestedRounding:
    def test_rounded_rates_produce_exact_0_8_ratio(self, api):
        """PRD §3.6: "For every record whose `count_in` is greater than zero, the pass rate is `count_passed` divided by `count_in`, rounded half-up to four decimal places, and the results are stored on `pass_rates` keyed by `class_label`; records with a zero `count_in` contribute no rate."
        PRD §3.6: "Otherwise the ratio is the smallest pass rate divided by the largest pass rate — computed from the already-rounded four-decimal rates, with the division order pinned so that rounding happens per class first and the quotient is itself rounded half-up to four decimal places. The `adverse_impact_flag` is true exactly when the ratio is less than 0.80; a ratio of exactly 0.8000 is not flagged."

        Design: Difficulty/combinatorial_formula/adverse_impact_nested_rounding_order
        """
        study = create_study(
            name="StudyQ", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31",
        )
        analysis = validate_success(
            api.create_pipeline_analysis(
                create_pipeline_analysis_payload(
                    study["id"], stage="INTERVIEW",
                    records=[
                        {"class_label": "MAJORITY", "count_in": 100, "count_passed": 80},
                        {"class_label": "MINORITY", "count_in": 100, "count_passed": 64},
                    ],
                ),
                _analyst(),
            ),
            201,
        )
        # Per-class rounding first: 0.8000 and 0.6400 at 4dp.
        assert analysis["pass_rates"]["MAJORITY"] == pytest.approx(0.8, abs=1e-9)
        assert analysis["pass_rates"]["MINORITY"] == pytest.approx(0.64, abs=1e-9)
        # The ratio is computed FROM the rounded rates: ROUND(0.6400/0.8000, 4).
        assert analysis["adverse_impact_ratio"] == pytest.approx(0.8, abs=1e-9)
        assert analysis["adverse_impact_flag"] is False
        assert analysis["highest_rate_class"] == "MAJORITY"

    def test_one_person_change_flips_flag(self, api):
        """PRD §3.6: "The `adverse_impact_flag` is true exactly when the ratio is less than 0.80; a ratio of exactly 0.8000 is not flagged."
        PRD §3.6: "Otherwise the ratio is the smallest pass rate divided by the largest pass rate — computed from the already-rounded four-decimal rates, with the division order pinned so that rounding happens per class first and the quotient is itself rounded half-up to four decimal places."

        Design: Difficulty/combinatorial_formula/adverse_impact_nested_rounding_order
        """
        study = create_study(
            name="StudyQ", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31",
        )
        analysis = validate_success(
            api.create_pipeline_analysis(
                create_pipeline_analysis_payload(
                    study["id"], stage="OFFER",
                    records=[
                        {"class_label": "MAJORITY", "count_in": 100, "count_passed": 80},
                        {"class_label": "MINORITY", "count_in": 100, "count_passed": 63},
                    ],
                ),
                _analyst(),
            ),
            201,
        )
        # ROUND(0.6300 / 0.8000, 4) = 0.7875 < 0.80.
        assert analysis["adverse_impact_ratio"] == pytest.approx(0.7875, abs=1e-9)
        assert analysis["adverse_impact_flag"] is True
        assert analysis["highest_rate_class"] == "MAJORITY"


class TestFourFifthsBoundary:
    def test_ratio_exactly_at_threshold_not_flagged(self, api):
        """PRD §3.6: "The `adverse_impact_flag` is true exactly when the ratio is less than 0.80; a ratio of exactly 0.8000 is not flagged."
        PRD §3.6: "The `highest_rate_class` is the `class_label` holding the highest pass rate, with ties broken by the earliest record index in the `records` array."

        Design: Difficulty/boundary_precision_check/four_fifths_ratio_exactly_at_threshold_not_flagged
        """
        study = create_study(
            name="StudyH", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31",
        )
        analysis = validate_success(
            api.create_pipeline_analysis(
                create_pipeline_analysis_payload(
                    study["id"], stage="HIRE",
                    records=[
                        {"class_label": "MAJORITY", "count_in": 100, "count_passed": 80},
                        {"class_label": "MINORITY", "count_in": 100, "count_passed": 64},
                    ],
                ),
                _analyst(),
            ),
            201,
        )
        # The boundary value itself is compliant: strict < 0.80 is required.
        assert analysis["adverse_impact_ratio"] == pytest.approx(0.8, abs=1e-9)
        assert analysis["adverse_impact_flag"] is False
        assert analysis["highest_rate_class"] == "MAJORITY"

    def test_ratio_one_step_below_threshold_flagged(self, api):
        """PRD §3.6: "The `adverse_impact_flag` is true exactly when the ratio is less than 0.80; a ratio of exactly 0.8000 is not flagged."

        Design: Difficulty/boundary_precision_check/four_fifths_ratio_exactly_at_threshold_not_flagged
        """
        study = create_study(
            name="StudyH", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31",
        )
        analysis = validate_success(
            api.create_pipeline_analysis(
                create_pipeline_analysis_payload(
                    study["id"], stage="HIRE",
                    records=[
                        {"class_label": "MAJORITY", "count_in": 100, "count_passed": 80},
                        {"class_label": "MINORITY", "count_in": 100, "count_passed": 63},
                    ],
                ),
                _analyst(),
            ),
            201,
        )
        # 0.7875 < 0.80: the strict less-than fires one step below the boundary.
        assert analysis["adverse_impact_ratio"] == pytest.approx(0.7875, abs=1e-9)
        assert analysis["adverse_impact_flag"] is True


class TestPipelineRecordValidation:
    def test_pipeline_invalid_record_rejected(self, api):
        """PRD §3.6: "The payload's `records` array must be non-empty, and each record carries a `class_label`, a `count_in` of zero or greater, and a `count_passed` of zero or greater that may not exceed its own `count_in`; a record with `count_passed` greater than `count_in`, any negative count, or an empty `records` array is rejected with `ERR_INVALID_PIPELINE_RECORD`."

        Design: Corner/validations/pipeline_invalid_record_rejected
        """
        study = create_study(
            name="PI", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31",
        )
        # count_passed 11 exceeds count_in 10.
        res1 = api.create_pipeline_analysis(
            create_pipeline_analysis_payload(
                study["id"], stage="SCREEN",
                records=[{"class_label": "A", "count_in": 10, "count_passed": 11}],
            ),
            _analyst(),
        )
        validate_error(res1, ApiErrorId.ERR_INVALID_PIPELINE_RECORD)
        # An empty records array is rejected.
        res2 = api.create_pipeline_analysis(
            create_pipeline_analysis_payload(
                study["id"], stage="SCREEN", records=[],
            ),
            _analyst(),
        )
        validate_error(res2, ApiErrorId.ERR_INVALID_PIPELINE_RECORD)
