"""The two composite variants, the per-item rounding order, and the penalty ladder."""
import pytest

from test_helpers import (
    ADMIN_HEADERS,
    SCORE_SHEET_ONE_CRITICAL,
    api_client,
    assert_audit_visit,
    assert_grade_matches_composite,
    make_auditor_headers,
    rescore_payload,
    setup_finalized_visit_with_health,
    setup_submitted_visit,
    validate_success,
)


class TestCompositeVariants:
    def test_submission_computes_the_provisional_composite_and_grade(self):
        """The provisional composite weights the base score and food safety only.

        PRD: "Under the `PROVISIONAL` variant, `composite_score` is the base score
        multiplied by six tenths plus `food_safety_percent` multiplied by four tenths,
        rounded half up to two decimal places — food safety is thus double-counted by
        design, once inside the base score and once alongside it."

        Design: Difficulty/dual_variant_calc/visit_composite_provisional_versus_final_diverges_and_flips_grade
        """
        program = setup_submitted_visit(sheet=SCORE_SHEET_ONE_CRITICAL)
        visit = program["visit"]
        assert_audit_visit(visit)

        assert visit["status"] == "SUBMITTED", "submission advances IN_PROGRESS to SUBMITTED"
        assert visit["food_safety_percent"] == pytest.approx(95.00, abs=0.01)
        assert visit["brand_standards_percent"] == pytest.approx(90.00, abs=0.01)
        assert visit["facility_percent"] == pytest.approx(91.67, abs=0.01)
        assert visit["critical_violation_count"] == 1
        assert visit["critical_penalty_points"] == pytest.approx(5.00, abs=0.01)
        assert visit["composite_score"] == pytest.approx(90.70, abs=0.01), \
            "0.60 * 87.83 + 0.40 * 95.00 rounds to 90.70"
        assert visit["composite_variant"] == "PROVISIONAL"
        assert visit["grade"] == "PASS", "a composite of exactly 90.70 grades PASS"
        assert visit["health_component_percent"] is None, \
            "no health-department figure participates in a provisional composite"
        assert visit["linked_health_inspection_id"] is None
        assert_grade_matches_composite(visit)

    def test_finalization_admits_the_health_component_and_flips_the_grade(self):
        """The final composite dilutes the rubric with the health figure.

        PRD: "The `FINAL` variant admits the health figure and dilutes the rubric:
        `composite_score` becomes the base score multiplied by forty-five hundredths,
        plus `food_safety_percent` multiplied by three tenths, plus
        `health_component_percent` multiplied by twenty-five hundredths, rounded half up
        to two decimal places."

        Design: Difficulty/dual_variant_calc/visit_composite_provisional_versus_final_diverges_and_flips_grade
        """
        program = setup_finalized_visit_with_health(
            points_scored=74, letter_grade="C", sheet=SCORE_SHEET_ONE_CRITICAL,
        )
        visit = program["visit"]
        assert_audit_visit(visit)

        assert visit["status"] == "FINALIZED"
        assert visit["composite_variant"] == "FINAL"
        assert visit["health_component_percent"] == pytest.approx(74.00, abs=0.01), \
            "74 of 100 posted as a C caps at 79.00 and therefore contributes 74.00"
        assert visit["linked_health_inspection_id"] == program["health_inspection"]["id"]
        assert visit["composite_score"] == pytest.approx(86.52, abs=0.01), \
            "0.45 * 87.83 + 0.30 * 95.00 + 0.25 * 74.00 rounds to 86.52"
        assert visit["grade"] == "CONDITIONAL", \
            "the diluted composite drops out of the PASS band"
        assert_grade_matches_composite(visit)

    def test_the_two_variants_disagree_on_one_unchanged_score_sheet(self):
        """The same scored items yield different composites at submit and finalize.

        PRD: "Because the weights differ from the provisional set, an identical set of
        scored items yields a different composite at finalization than it did at
        submission, and can therefore yield a different `grade`."

        Design: Difficulty/dual_variant_calc/visit_composite_provisional_versus_final_diverges_and_flips_grade
        """
        program = setup_finalized_visit_with_health(
            points_scored=74, letter_grade="C", sheet=SCORE_SHEET_ONE_CRITICAL,
        )
        finalized = program["visit"]

        # The section percents are untouched by finalization: only the weights moved.
        assert finalized["food_safety_percent"] == pytest.approx(95.00, abs=0.01)
        assert finalized["brand_standards_percent"] == pytest.approx(90.00, abs=0.01)
        assert finalized["facility_percent"] == pytest.approx(91.67, abs=0.01)
        assert finalized["critical_violation_count"] == 1
        assert finalized["critical_penalty_points"] == pytest.approx(5.00, abs=0.01)

        provisional_composite = 90.70
        delta = provisional_composite - finalized["composite_score"]
        assert delta == pytest.approx(4.18, abs=0.01), \
            "the variant switch moves the composite by exactly 4.18 points"
        assert finalized["grade"] == "CONDITIONAL", "the provisional grade had been PASS"


class TestPerItemRoundingOrder:
    def test_section_percents_are_means_of_individually_rounded_item_percents(self):
        """Each item is rounded before the section mean is taken.

        PRD: "The section percent is therefore the mean of the individually rounded
        per-item percentages, *not* the ratio of the section's total awarded points to
        its total maximum points; the two formulations produce different numbers and,
        through the composite, can produce a different grade."

        Design: Difficulty/combinatorial_formula/per_item_rounding_order_pinned_and_flips_the_grade
        """
        program = setup_submitted_visit(sheet=SCORE_SHEET_ONE_CRITICAL)
        visit = program["visit"]

        assert visit["food_safety_percent"] == pytest.approx(95.00, abs=0.01), \
            "mean of 90.00 and 100.00 is 95.00, not the 94.00 of 47 over 50"
        assert visit["facility_percent"] == pytest.approx(91.67, abs=0.01), \
            "mean of 83.33 and 100.00 is 91.67, not the 90.00 of 18 over 20"
        assert visit["brand_standards_percent"] == pytest.approx(90.00, abs=0.01), \
            "mean of 80.00 and 100.00 is 90.00"

    def test_the_rounding_order_decides_the_grade(self):
        """The rounded-first arithmetic lands the visit in the PASS band.

        PRD: "Divide that awarded figure by the item's `max_points`, multiply by 100, and
        round half up to two decimal places — **this per-item rounding happens first**."

        Design: Difficulty/combinatorial_formula/per_item_rounding_order_pinned_and_flips_the_grade
        """
        program = setup_submitted_visit(sheet=SCORE_SHEET_ONE_CRITICAL)
        visit = program["visit"]

        assert visit["critical_penalty_points"] == pytest.approx(5.00, abs=0.01)
        assert visit["composite_score"] == pytest.approx(90.70, abs=0.01), \
            "rounding each item first yields 90.70; totalling points first yields 89.80"
        assert visit["grade"] == "PASS", \
            "90.70 clears the 90.00 band, where the point-total formulation would not"
        assert_grade_matches_composite(visit)


class TestCriticalViolationBoundary:
    def test_one_critical_violation_costs_five_penalty_points(self):
        """A single critical violation steps the ladder to 5.00.

        PRD: "The penalty ladder is stepped, not linear: `critical_penalty_points` is
        0.00 when there are no critical violations, 5.00 when there is exactly one, 12.00
        when there are exactly two, and 25.00 when there are three or more."

        Design: Difficulty/boundary_precision_check/critical_violation_count_boundary_one_versus_two_flips_penalty_and_grade
        """
        program = setup_submitted_visit(sheet=SCORE_SHEET_ONE_CRITICAL)
        visit = program["visit"]

        assert visit["critical_violation_count"] == 1
        assert visit["critical_penalty_points"] == pytest.approx(5.00, abs=0.01)
        assert visit["composite_score"] == pytest.approx(90.70, abs=0.01)
        assert visit["grade"] == "PASS", "one critical violation does not force a FAIL"

    def test_the_second_critical_violation_forces_fail_regardless_of_the_score(self):
        """Crossing from one to two critical violations overrides the score bands.

        PRD: "If `critical_violation_count` is 2 or more, the grade is `FAIL` regardless
        of the score; this override outranks the score bands entirely."

        Design: Difficulty/boundary_precision_check/critical_violation_count_boundary_one_versus_two_flips_penalty_and_grade
        """
        program = setup_submitted_visit(sheet=SCORE_SHEET_ONE_CRITICAL)
        visit = program["visit"]
        auditor_headers = make_auditor_headers(program["auditor"]["id"])

        rescored = validate_success(
            api_client.rescore_audit_visit(
                visit["id"],
                rescore_payload(program["scored"]["FS-2"]["id"], 19, visit["version"]),
                auditor_headers,
            )
        )

        assert rescored["critical_violation_count"] == 2
        assert rescored["critical_penalty_points"] == pytest.approx(12.00, abs=0.01)
        assert rescored["food_safety_percent"] == pytest.approx(92.50, abs=0.01), \
            "mean of 90.00 and 95.00"
        assert rescored["composite_score"] == pytest.approx(84.75, abs=0.01), \
            "0.60 * 79.58 + 0.40 * 92.50 rounds to 84.75"
        assert rescored["grade"] == "FAIL", \
            "84.75 would grade CONDITIONAL but two critical violations override it"
        assert rescored["rescore_count"] == 1
        assert rescored["status"] == "SUBMITTED", "a rescore is a self-loop on SUBMITTED"
        assert_grade_matches_composite(rescored)

        reread = validate_success(api_client.get_audit_visit(visit["id"], ADMIN_HEADERS))
        assert reread["grade"] == "FAIL"
        assert reread["finalized_at"] is None
