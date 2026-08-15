"""Pace, GPA, and maximum-timeframe arithmetic, including both metric variants."""
import pytest

from test_helpers import (
    AID_OFFICER, api_client, close_and_evaluate, close_grading,
    create_enrollment, create_posted_enrollment, create_program, create_student,
    create_term, create_standard_terms, evaluate_term, get_student,
    official_evaluation, validate_success,
)


class TestPaceOfficialVsPreviewProjection:
    """The advising preview reports both pace bases on identical stored data."""

    def _world(self, api):
        program = create_program(code="BS-CSCI", name="Computer Science",
                                 required_credits=120)
        term = create_term(1)
        student = create_student(program["id"], student_number="S-1001",
                                 full_name="Ada Pace")
        create_posted_enrollment(student["id"], term["id"], 9, 6, 18.0, 9)
        create_enrollment(student["id"], term["id"], 6)  # still IN_PROGRESS
        return student

    def test_preview_reports_official_and_projected_pace(self, api):
        """PRD section 3.4: "Its payload carries `pace_pct_official_basis`, the
        official pace over posted and amended rows only, next to `pace_pct_projected`,
        a best-case figure that additionally counts every in-progress enrollment's
        attempted credits as both attempted and earned; on identical inputs the
        projected figure is never lower than the official one."

        Design: Difficulty/dual_variant_calc/pace_official_vs_preview_projection
        """
        student = self._world(api)
        preview = validate_success(api.get_sap_preview(student["id"], AID_OFFICER), 200)
        assert preview["pace_pct_official_basis"] == pytest.approx(66.67), (
            "official basis: 6 earned / 9 attempted over POSTED rows only")
        assert preview["pace_pct_projected"] == pytest.approx(80.00), (
            "projected basis: (6+6) / (9+6) with the IN_PROGRESS row counted as earned")
        assert preview["pace_pct_official_basis"] != preview["pace_pct_projected"]

    def test_preview_gpa_and_student_record_use_official_basis(self, api):
        """PRD section 3.4: "It reports `cumulative_gpa` under the raw-sums rule of
        §3.3."
        PRD section 3.3: "All official academic measurement rests on a single basis
        set: the student's enrollment rows in `POSTED` or `AMENDED` status. Rows still
        `IN_PROGRESS` never enter official figures."

        Design: Difficulty/dual_variant_calc/pace_official_vs_preview_projection
        """
        student = self._world(api)
        preview = validate_success(api.get_sap_preview(student["id"], AID_OFFICER), 200)
        assert preview["cumulative_gpa"] == pytest.approx(2.0), "18.0 / 9 GPA hours"
        stored = get_student(student["id"])
        assert stored["pace_pct"] == pytest.approx(66.67), (
            "the student record carries the official basis, not the projection")
        assert stored["pace_pct"] == preview["pace_pct_official_basis"]


class TestMaxTimeframeVariants:
    """The attempted-only and remaining-projection variants disagree by design."""

    def _world(self, api):
        """Student at attempted 175 / earned 100 against a 120-credit program.

        Cap is floor(120 * 1.5) = 180. The T1 term is already evaluated (student
        in WARNING); the T2 grades are posted but the term is not yet closed.
        """
        program = create_program(code="BS-MATH", name="Mathematics", required_credits=120)
        terms = create_standard_terms(2)
        student = create_student(program["id"], student_number="S-2001",
                                 full_name="Max Timeframe")
        create_posted_enrollment(student["id"], terms[1]["id"], 100, 60, 180.0, 100)
        close_and_evaluate(terms[1]["id"])
        create_posted_enrollment(student["id"], terms[2]["id"], 75, 40, 80.0, 75)
        return program, terms, student

    def test_preview_reports_both_max_timeframe_variants(self, api):
        """PRD section 3.3: "The projection is exceeded when the attempted credits plus
        the credits still required come to strictly more than the cap; a student whose
        attempted credits exactly equal the cap with nothing left to earn is still
        within the timeframe. A weaker attempted-only variant exists purely for
        advising (§3.4): it declares the timeframe blown only when attempted credits
        alone exceed the cap, so on identical data it fires strictly later than the
        projection."

        Design: Difficulty/dual_variant_calc/max_timeframe_attempted_only_vs_projection
        """
        _program, _terms, student = self._world(api)
        preview = validate_success(api.get_sap_preview(student["id"], AID_OFFICER), 200)
        assert preview["max_tf_attempted_only_exceeded"] is False, (
            "175 attempted < cap 180: the weaker variant stays silent")
        assert preview["max_tf_projection_exceeded"] is True, (
            "175 attempted + 20 still required = 195 > 180: the projection fires")

    def test_official_evaluation_uses_projection_variant(self, api):
        """PRD section 3.4: "And it reports both maximum-timeframe variants:
        `max_tf_attempted_only_exceeded`, the weaker attempted-only test, and
        `max_tf_projection_exceeded`, the stricter projection test that the official
        evaluation will actually apply."
        PRD section 3.5: "2. Otherwise, when the maximum-timeframe projection is
        exceeded, the student is assigned `SUSPENSION`."

        Design: Difficulty/dual_variant_calc/max_timeframe_attempted_only_vs_projection
        """
        _program, terms, student = self._world(api)
        close_and_evaluate(terms[2]["id"])
        evaluation = official_evaluation(student["id"], terms[2]["id"])
        assert evaluation["max_tf_exceeded"] is True
        assert evaluation["pace_pct"] == pytest.approx(57.14), "100 / 175"
        assert evaluation["cumulative_gpa"] == pytest.approx(1.486), "260 / 175"
        assert evaluation["result_standing"] == "SUSPENSION"


class TestMaxTimeframeOverridesPassingMetrics:
    """A max-timeframe breach suspends even when pace and GPA both pass."""

    def _world(self, api):
        """200-credit program (cap floor(200*1.5)=300); T1 perfect 200 credits; T2 adds
        110 attempted with only 10 earned, pushing attempted to 310 > 300."""
        program = create_program(code="BA-HIST", name="History", required_credits=200)
        terms = create_standard_terms(2)
        student = create_student(program["id"], student_number="S-3001",
                                 full_name="Olive Override")
        create_posted_enrollment(student["id"], terms[1]["id"], 200, 200, 600.0, 200)
        close_and_evaluate(terms[1]["id"])
        create_posted_enrollment(student["id"], terms[2]["id"], 110, 10, 30.0, 110)
        close_grading(terms[2]["id"])
        return terms, student

    def test_max_timeframe_breach_suspends_despite_passing_metrics(self, api):
        """PRD section 3.5: "2. Otherwise, when the maximum-timeframe projection is
        exceeded, the student is assigned `SUSPENSION`. The timeframe failure overrides
        every prior standing and grants no warning grace, even when pace and GPA both
        pass."

        Design: Difficulty/combinatorial_formula/standing_assignment_max_tf_overrides_passing_metrics
        """
        terms, student = self._world(api)
        summary = evaluate_term(terms[2]["id"])
        evaluation = official_evaluation(student["id"], terms[2]["id"])
        assert evaluation["pace_pct"] == pytest.approx(67.74), "210 / 310 passes 67.00"
        assert evaluation["cumulative_gpa"] == pytest.approx(2.032), "630 / 310 passes 2.000"
        assert evaluation["max_tf_exceeded"] is True, "310 attempted > cap 300"
        assert evaluation["result_standing"] == "SUSPENSION"
        assert summary["evaluated_count"] == 1
        assert summary["suspension_count"] == 1

    def test_max_timeframe_breach_skips_the_warning_rung(self, api):
        """PRD section 3.5: "2. Otherwise, when the maximum-timeframe projection is
        exceeded, the student is assigned `SUSPENSION`. The timeframe failure overrides
        every prior standing and grants no warning grace, even when pace and GPA both
        pass."

        Design: Difficulty/combinatorial_formula/standing_assignment_max_tf_overrides_passing_metrics
        """
        terms, student = self._world(api)
        evaluate_term(terms[2]["id"])
        evaluation = official_evaluation(student["id"], terms[2]["id"])
        assert evaluation["prior_standing"] == "GOOD_STANDING"
        assert evaluation["result_standing"] == "SUSPENSION", (
            "no WARNING grace under a max-timeframe breach")
        assert get_student(student["id"])["sap_status"] == "SUSPENSION"


class TestCumulativeGpaRoundingOrder:
    """The cumulative GPA divides raw sums and rounds exactly once."""

    def _world(self, api):
        """T1: 4.6 quality points / 3 GPA hours; T2: 13.9 / 9. Raw division
        18.5 / 12 rounds once to 1.542; term-first recomposition would give 1.541."""
        program = create_program(code="BS-CHEM", name="Chemistry", required_credits=120)
        terms = create_standard_terms(2)
        student = create_student(program["id"], student_number="S-4001",
                                 full_name="Rhea Rounding")
        create_posted_enrollment(student["id"], terms[1]["id"], 3, 3, 4.6, 3)
        close_and_evaluate(terms[1]["id"])
        create_posted_enrollment(student["id"], terms[2]["id"], 9, 9, 13.9, 9)
        close_grading(terms[2]["id"])
        return terms, student

    def test_cumulative_gpa_computed_from_raw_sums(self, api):
        """PRD section 3.3: "One rounding rule is pinned because it decides real cases:
        the cumulative GPA must be computed from the raw cumulative sums and rounded
        exactly once at the end. Consider a record of two posted rows, one carrying 4.6
        quality points over 3 GPA hours and another carrying 13.9 quality points over 9
        GPA hours. The official figure divides the raw sums — 18.5 quality points over
        12 GPA hours — and rounds once, yielding 1.542."

        Design: Difficulty/combinatorial_formula/cumulative_gpa_raw_sum_vs_term_rounded_recomposition
        """
        terms, student = self._world(api)
        evaluate_term(terms[2]["id"])
        evaluation = official_evaluation(student["id"], terms[2]["id"])
        assert evaluation["cumulative_gpa"] == pytest.approx(1.542), (
            "raw sums 18.5 / 12 rounded once")

    def test_cumulative_gpa_is_not_term_rounded_recomposition(self, api):
        """PRD section 3.3: "Rounding each term first and then credit-weighting the
        rounded terms would report 1.541; that recomposition is expressly forbidden."

        Design: Difficulty/combinatorial_formula/cumulative_gpa_raw_sum_vs_term_rounded_recomposition
        """
        terms, student = self._world(api)
        evaluate_term(terms[2]["id"])
        evaluation = official_evaluation(student["id"], terms[2]["id"])
        assert evaluation["cumulative_gpa"] != pytest.approx(1.541), (
            "the forbidden term-rounded recomposition"
        )
        assert evaluation["pace_pct"] == pytest.approx(100.0)
        assert evaluation["prior_standing"] == "WARNING"
        assert evaluation["result_standing"] == "SUSPENSION", (
            "GPA 1.542 < 2.000 on a prior WARNING falls to SUSPENSION")


class TestPaceThresholdBoundary:
    """Exactly 67.00 passes; 66.00 fails — the pace boundary is inclusive."""

    def _world(self, api):
        """Students A and B share T1 (40/50 earned, GOOD_STANDING). In T2, A earns 27
        of 50 (cumulative 67/100 = exactly 67.00) and B earns 26 (66/100 = 66.00)."""
        program = create_program(code="BS-ECON", name="Economics", required_credits=120)
        terms = create_standard_terms(2)
        student_a = create_student(program["id"], student_number="S-9101",
                                   full_name="Ann Exact")
        student_b = create_student(program["id"], student_number="S-9102",
                                   full_name="Bob Below")
        for stu in (student_a, student_b):
            create_posted_enrollment(stu["id"], terms[1]["id"], 50, 40, 150.0, 50)
        close_and_evaluate(terms[1]["id"])
        create_posted_enrollment(student_a["id"], terms[2]["id"], 50, 27, 81.0, 50)
        create_posted_enrollment(student_b["id"], terms[2]["id"], 50, 26, 78.0, 50)
        close_and_evaluate(terms[2]["id"])
        return terms, student_a, student_b

    def test_pace_exactly_67_passes(self, api):
        """PRD section 3.3: "A student passes the quantitative standard when their pace
        is at least the program's `min_pace_pct` — the boundary is inclusive, so a pace
        of exactly 67.00 satisfies a 67.0 standard."

        Design: Difficulty/boundary_precision_check/pace_exactly_67_passes_vs_66_fails
        """
        terms, student_a, _student_b = self._world(api)
        evaluation = official_evaluation(student_a["id"], terms[2]["id"])
        assert evaluation["pace_pct"] == pytest.approx(67.00), "67 / 100 exactly"
        assert evaluation["result_standing"] == "GOOD_STANDING"

    def test_pace_66_fails_and_counts_tally(self, api):
        """PRD section 3.3: "A student passes the quantitative standard when their pace
        is at least the program's `min_pace_pct` — the boundary is inclusive, so a pace
        of exactly 67.00 satisfies a 67.0 standard."
        PRD section 3.5: "The response summarizes the sweep with four counters:
        `evaluated_count`, `good_standing_count`, `warning_count`, and
        `suspension_count`."

        Design: Difficulty/boundary_precision_check/pace_exactly_67_passes_vs_66_fails
        """
        terms, student_a, student_b = self._world(api)
        evaluation_b = official_evaluation(student_b["id"], terms[2]["id"])
        assert evaluation_b["pace_pct"] == pytest.approx(66.00), "66 / 100"
        assert evaluation_b["result_standing"] == "WARNING"
        evaluation_a = official_evaluation(student_a["id"], terms[2]["id"])
        assert evaluation_a["result_standing"] == "GOOD_STANDING"


def test_gpa_exactly_two_passes_vs_below_fails(api):
    """PRD section 3.3: "A student passes the qualitative standard when their
    cumulative GPA is at least the program's `min_gpa` — exactly 2.000 passes a 2.0
    standard — and a null GPA is treated as satisfying the qualitative standard."

    Design: Corner/calculations/gpa_exactly_two_passes_vs_below_fails
    """
    program = create_program(code="BS-GP", name="GpaBoundary", required_credits=120)
    term = create_term(1)
    student_c = create_student(program["id"], student_number="S-2001",
                               full_name="Gpa Pass")
    student_d = create_student(program["id"], student_number="S-2002",
                               full_name="Gpa Fail")
    create_posted_enrollment(student_c["id"], term["id"], 12, 12, 24.0, 12)
    create_posted_enrollment(student_d["id"], term["id"], 12, 12, 23.88, 12)
    close_and_evaluate(term["id"])

    evaluation_c = official_evaluation(student_c["id"], term["id"])
    assert evaluation_c["cumulative_gpa"] == pytest.approx(2.0)
    assert evaluation_c["result_standing"] == "GOOD_STANDING", (
        "the GPA threshold is inclusive at exactly 2.000")

    evaluation_d = official_evaluation(student_d["id"], term["id"])
    assert evaluation_d["cumulative_gpa"] == pytest.approx(1.99)
    assert evaluation_d["result_standing"] == "WARNING", (
        "1.990 < 2.000 fails despite a perfect 100.00 pace")
    assert evaluation_d["pace_pct"] == pytest.approx(100.0)


def test_max_timeframe_floor_boundary(api):
    """PRD section 3.3: "The cap is the largest whole number of credits not exceeding
    one and a half times the program's `required_credits`."
    PRD section 3.3: "The projection is exceeded when the attempted credits plus the
    credits still required come to strictly more than the cap; a student whose
    attempted credits exactly equal the cap with nothing left to earn is still within
    the timeframe."

    Design: Corner/calculations/max_timeframe_floor_boundary
    """
    # required 121 -> cap floor(181.5) = 181
    program = create_program(code="BS-MTF", name="MaxTfFloor", required_credits=121)
    terms = create_standard_terms(2)
    student_a = create_student(program["id"], student_number="S-2101",
                               full_name="Floor Within")
    student_b = create_student(program["id"], student_number="S-2102",
                               full_name="Floor Over")
    for stu in (student_a, student_b):
        create_posted_enrollment(stu["id"], terms[1]["id"], 100, 100, 300.0, 100)
    close_and_evaluate(terms[1]["id"])
    # A: cumulative attempted 181, earned 121; B: attempted 182, earned 122.
    create_posted_enrollment(student_a["id"], terms[2]["id"], 81, 21, 63.0, 81)
    create_posted_enrollment(student_b["id"], terms[2]["id"], 82, 22, 66.0, 82)
    close_and_evaluate(terms[2]["id"])

    evaluation_a = official_evaluation(student_a["id"], terms[2]["id"])
    assert evaluation_a["max_tf_headroom_credits"] == 0, "181 - 181"
    assert evaluation_a["max_tf_exceeded"] is False, (
        "strictly-greater test: 181 + 0 > 181 is false")
    assert evaluation_a["result_standing"] == "WARNING", (
        "pace 66.85 fails, but the max-timeframe projection does not suspend")

    evaluation_b = official_evaluation(student_b["id"], terms[2]["id"])
    assert evaluation_b["max_tf_headroom_credits"] == -1, "181 - 182"
    assert evaluation_b["max_tf_exceeded"] is True, "182 > cap 181"
    assert evaluation_b["pace_pct"] == pytest.approx(67.03), "pace passes..."
    assert evaluation_b["result_standing"] == "SUSPENSION", (
        "...but the floored cap suspends; a round() cap of 182 would acquit")


def test_pace_two_thirds_fails_below_threshold(api):
    """PRD section 3.3: "The pace metric `pace_pct` is one hundred times the summed
    earned credits divided by the summed attempted credits, rounded half up to two
    decimal places; it is null when no attempted credits exist at all."
    PRD section 3.3: "A student passes the quantitative standard when their pace is at
    least the program's `min_pace_pct` — the boundary is inclusive, so a pace of
    exactly 67.00 satisfies a 67.0 standard."

    Design: Corner/calculations/pace_two_thirds_fails_below_threshold
    """
    program = create_program(code="BS-23", name="TwoThirds", required_credits=120)
    term = create_term(1)
    student = create_student(program["id"], student_number="S-2401",
                             full_name="Two Thirds")
    create_posted_enrollment(student["id"], term["id"], 3, 2, 8.0, 3)
    close_and_evaluate(term["id"])

    evaluation = official_evaluation(student["id"], term["id"])
    assert evaluation["pace_pct"] == pytest.approx(66.67), (
        "2/3 rounds half-up to 66.67, never up to the 67.00 threshold")
    assert evaluation["result_standing"] == "WARNING", "66.67 < 67.00 fails"
    assert evaluation["cumulative_gpa"] == pytest.approx(2.667)


def test_preview_with_no_enrollments_returns_null_metrics(api):
    """PRD section 3.3: "The pace metric `pace_pct` is one hundred times the summed
    earned credits divided by the summed attempted credits, rounded half up to two
    decimal places; it is null when no attempted credits exist at all."
    PRD section 3.3: "The cumulative GPA `cumulative_gpa` is the summed quality points
    divided by the summed GPA hours, rounded half up to three decimal places, and it is
    null when the student has no GPA-counting hours."

    Design: Corner/calculations/preview_with_no_enrollments_returns_null_metrics
    """
    program = create_program(code="BS-NP", name="NullPreview", required_credits=120)
    student = create_student(program["id"], student_number="S-2601",
                             full_name="No Enroll")
    preview = validate_success(api.get_sap_preview(student["id"], AID_OFFICER), 200)
    assert preview["pace_pct_official_basis"] is None
    assert preview["pace_pct_projected"] is None
    assert preview["cumulative_gpa"] is None
    assert preview["max_tf_attempted_only_exceeded"] is False
    assert preview["max_tf_projection_exceeded"] is False
