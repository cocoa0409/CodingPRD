"""Credit conversion variants: provisional vs final award math, per-line
rounding order, transfer GPA rounding, and the two degree-audit variants."""
import pytest

from test_helpers import (
    validate_success,
    get_success_data,
    api_client,
    TEST_USERS,
    make_student_headers,
    create_transcript_course_payload,
    fixtures,
)

ADMIN = TEST_USERS["admin_headers"]
STAFF = TEST_USERS["staff_headers"]
EVALUATOR = TEST_USERS["evaluator_headers"]
EVAL_A = fixtures.EVAL_A
EVAL_B = fixtures.EVAL_B


def _setup_quarter_single_line(course_hours=4.0, external_hours=4.5, grade="B"):
    """QUARTER partner + one-line AUTO_MATCHED evaluation in IN_REVIEW."""
    return fixtures.setup_evaluation_in_review(
        partner_credit_system="QUARTER",
        course_kwargs={"code": "MATH-150", "title": "Calculus I", "credit_hours": course_hours,
                       "department": "MATH"},
        equivalency_kwargs={"external_course_code": "MATH-101", "external_title": "Intro Calc",
                            "external_credit_hours": external_hours},
        transcript_courses=[create_transcript_course_payload(
            external_course_code="MATH-101", title="Intro Calc",
            credit_hours=external_hours, grade=grade)],
        student_major="MATH",
    )


class TestLineCreditProvisionalVsFinalConversion:
    def test_provisional_estimate_at_intake(self):
        """PRD §3.5: "multiply the line's `external_credit_hours` by an estimate
        factor selected from the partner's `credit_system` — 0.75 for `QUARTER`
        partners, 1.0 for `SEMESTER` — round the product half-up to one decimal
        place, and then take the smaller of that rounded value and the matched
        course's `credit_hours`."

        Design: Difficulty/dual_variant_calc/line_credit_provisional_vs_final_conversion
        """
        ctx = _setup_quarter_single_line()
        line = get_success_data(api_client.get_line_item(ctx["lines"][0]["id"], EVALUATOR))
        assert line["provisional_credits"] == pytest.approx(3.4, abs=1e-9), (
            "provisional = min(round_half_up(4.5*0.75, 1)=3.4, cap 4.0)"
        )

    def test_final_award_diverges_after_adopt_and_finalize(self):
        """PRD §3.5: "The **final variant** governs adoption and finalization:
        multiply `external_credit_hours` by the exact factor — precisely two-thirds
        for `QUARTER`, 1.0 for `SEMESTER` — round to the nearest half credit by
        doubling the product, rounding half-up to a whole number, and halving, then
        cap at the adopted course's `credit_hours`."
        PRD §3.5: "The system carries two deliberate credit variants, and identical
        input data yields different numbers under each."

        Design: Difficulty/dual_variant_calc/line_credit_provisional_vs_final_conversion
        """
        ctx = _setup_quarter_single_line()
        line_id = ctx["lines"][0]["id"]
        provisional_before = get_success_data(
            api_client.get_line_item(line_id, EVALUATOR)
        )["provisional_credits"]

        get_success_data(api_client.adopt_line_item(line_id, {}, EVALUATOR))
        evaluation = fixtures.finalize_evaluation(ctx["evaluation"]["id"], EVAL_A)

        line = get_success_data(api_client.get_line_item(line_id, EVALUATOR))
        # half-step(4.5 * 2/3 = 3.0) = 3.0, capped by 4.0
        assert line["awarded_credits"] == pytest.approx(3.0, abs=1e-9)
        # The two variants coexist: provisional stays 3.4, final is 3.0.
        assert line["provisional_credits"] == pytest.approx(3.4, abs=1e-9)
        assert line["awarded_credits"] != line["provisional_credits"]
        assert evaluation["awarded_credits_total"] == pytest.approx(3.0, abs=1e-9)


class TestProvisionalTotalPerLineRoundingOrder:
    def _setup_three_line_quarter_evaluation(self):
        partner = fixtures.create_partner(
            name="Quarter College", code="QC", credit_system="QUARTER"
        )
        c1 = fixtures.create_course(code="MATH-150", credit_hours=4.0, department="MATH")
        c2 = fixtures.create_course(code="ENGL-150", title="Literature", credit_hours=4.0, department="ENGL")
        c3 = fixtures.create_course(code="HIST-150", title="Seminar", credit_hours=2.0, department="HIST")
        agreement = fixtures.create_agreement(partner["id"])
        fixtures.activate_agreement(agreement["id"])
        fixtures.add_equivalency(agreement["id"], c1["id"], "Q-101", external_credit_hours=4.5)
        fixtures.add_equivalency(agreement["id"], c2["id"], "Q-102", external_credit_hours=4.5)
        fixtures.add_equivalency(agreement["id"], c3["id"], "Q-103", external_credit_hours=2.25)
        student = fixtures.create_student(major="MATH")
        transcript = fixtures.create_verified_transcript(
            student["id"], partner["id"],
            courses=[
                create_transcript_course_payload(external_course_code="Q-101", title="Q101", credit_hours=4.5, grade="B"),
                create_transcript_course_payload(external_course_code="Q-102", title="Q102", credit_hours=4.5, grade="B"),
                create_transcript_course_payload(external_course_code="Q-103", title="Q103", credit_hours=2.25, grade="B"),
            ],
        )
        return student, transcript

    def test_provisional_total_sums_per_line_rounded_values(self):
        """PRD §3.4: "the evaluation's `provisional_credits_total` — the sum of the
        per-line rounded `provisional_credits` values over lines holding one, with
        no second rounding".
        PRD §2.6: "Evaluation-level provisional totals sum the already-rounded
        per-line values and apply no second rounding — summing unrounded raw values
        and rounding once at the end is forbidden, because it yields a different
        number."

        Design: Difficulty/combinatorial_formula/provisional_total_per_line_rounding_order
        """
        student, transcript = self._setup_three_line_quarter_evaluation()
        evaluation = fixtures.create_evaluation(student["id"], transcript["id"])
        # Per line: round_half_up(4.5*0.75,1)=3.4, 3.4, round_half_up(2.25*0.75,1)=1.7
        # Sum of rounded: 8.5. Forbidden order (sum raw 8.4375 then round) gives 8.4.
        assert evaluation["provisional_credits_total"] == pytest.approx(8.5, abs=1e-9), (
            "per-line-then-sum order pinned: 3.4 + 3.4 + 1.7 = 8.5, not 8.4"
        )

    def test_per_line_provisional_values_individually_rounded(self):
        """PRD §2.6: "Provisional credit estimates are rounded to exactly one
        decimal place, and that rounding happens **before** any cap against a
        course's credit hours is applied."

        Design: Difficulty/combinatorial_formula/provisional_total_per_line_rounding_order
        """
        student, transcript = self._setup_three_line_quarter_evaluation()
        evaluation = fixtures.create_evaluation(student["id"], transcript["id"])
        lines = fixtures.get_evaluation_lines(evaluation["id"])
        by_code = {l["external_course_code"]: l for l in lines}
        assert by_code["Q-101"]["provisional_credits"] == pytest.approx(3.4, abs=1e-9)
        assert by_code["Q-102"]["provisional_credits"] == pytest.approx(3.4, abs=1e-9)
        # 2.25 * 0.75 = 1.6875 -> 1.7 (no cap: course allows 2.0)
        assert by_code["Q-103"]["provisional_credits"] == pytest.approx(1.7, abs=1e-9)


class TestDegreeProgressCertifiedVsProvisional:
    def _setup(self):
        """EV1 fully POSTED (M-101 A -> CMAT 4.0 MAJOR_CORE; E-201 B -> CENG 3.0
        GENED_COMMS); EV2 IN_REVIEW with H-301 line ADOPTED at 5.0; one VERIFIED
        (not credited) PLA of 6.0."""
        partner = fixtures.create_partner(credit_system="SEMESTER")
        c_math = fixtures.create_course(code="MATH-150", credit_hours=4.0, department="MATH")
        c_eng = fixtures.create_course(code="ENG-110", title="Composition", credit_hours=3.0,
                                       department="ENGL", gened_tags=["GENED_COMMS"])
        c_hist = fixtures.create_course(code="HIST-100", title="World History", credit_hours=6.0,
                                        department="HIST")
        agreement = fixtures.create_agreement(partner["id"])
        fixtures.activate_agreement(agreement["id"])
        fixtures.add_equivalency(agreement["id"], c_math["id"], "M-101", external_credit_hours=4.0)
        fixtures.add_equivalency(agreement["id"], c_eng["id"], "E-201", external_credit_hours=3.0)
        fixtures.add_equivalency(agreement["id"], c_hist["id"], "H-301", external_credit_hours=5.0)
        student = fixtures.create_student(major="MATH")

        t1 = fixtures.create_verified_transcript(
            student["id"], partner["id"],
            courses=[
                create_transcript_course_payload(external_course_code="M-101", title="Calc", credit_hours=4.0, grade="A"),
                create_transcript_course_payload(external_course_code="E-201", title="Comp", credit_hours=3.0, grade="B"),
            ],
        )
        ev1 = fixtures.create_evaluation(student["id"], t1["id"])
        lines1 = fixtures.get_evaluation_lines(ev1["id"])
        fixtures.get_success_data(api_client.start_evaluation_review(ev1["id"], EVALUATOR))
        fixtures.adopt_all_lines(ev1["id"], lines1)
        fixtures.finalize_evaluation(ev1["id"], EVAL_A)
        fixtures.post_evaluation(ev1["id"], EVAL_B)

        t2 = fixtures.create_verified_transcript(
            student["id"], partner["id"],
            courses=[create_transcript_course_payload(external_course_code="H-301", title="History",
                                                      credit_hours=5.0, grade="A")],
            term_completed="2025-08-15",
        )
        ev2 = fixtures.create_evaluation(student["id"], t2["id"])
        lines2 = fixtures.get_evaluation_lines(ev2["id"])
        fixtures.get_success_data(api_client.start_evaluation_review(ev2["id"], EVALUATOR))
        fixtures.adopt_all_lines(ev2["id"], lines2)

        pla = fixtures.create_pla(student["id"], claimed_credits=6.0)
        fixtures.verify_pla(pla["id"], 6.0)
        return student

    def test_certified_counts_only_posted_and_credited(self):
        """PRD §3.8: "`CERTIFIED` (the default) counts only certified sources —
        requirement rows sourced from `POSTED` lines or `CREDITED` assessments".

        Design: Difficulty/dual_variant_calc/degree_progress_certified_vs_provisional
        """
        student = self._setup()
        progress = get_success_data(
            api_client.get_degree_progress(student["id"], EVALUATOR, params={"variant": "CERTIFIED"})
        )
        assert progress["variant"] == "CERTIFIED"
        # Only the posted applications: 4.0 MAJOR_CORE + 3.0 GENED_COMMS.
        assert progress["total_applied_credits"] == pytest.approx(7.0, abs=1e-9)

    def test_provisional_adds_adopted_and_verified_projections(self):
        """PRD §3.8: "`PROVISIONAL` adds projections for `ADOPTED` lines at their
        full `awarded_credits` into their natural slot with no waterfall truncation,
        and for `VERIFIED` assessments at their `verified_credits`, so identical
        student data yields a larger total under `PROVISIONAL`."

        Design: Difficulty/dual_variant_calc/degree_progress_certified_vs_provisional
        """
        student = self._setup()
        certified = get_success_data(
            api_client.get_degree_progress(student["id"], EVALUATOR, params={"variant": "CERTIFIED"})
        )
        provisional = get_success_data(
            api_client.get_degree_progress(student["id"], EVALUATOR, params={"variant": "PROVISIONAL"})
        )
        # 7.0 certified + 5.0 ADOPTED projection + 6.0 VERIFIED PLA projection.
        assert provisional["total_applied_credits"] == pytest.approx(18.0, abs=1e-9)
        assert certified["total_applied_credits"] == pytest.approx(7.0, abs=1e-9)
        assert provisional["total_applied_credits"] > certified["total_applied_credits"]


class TestTransferGpaPerLineRoundingPrecision:
    def _setup_posted_two_lines(self):
        """SEMESTER partner; HIST courses capped 2.5 and 1.5; both lines land in
        FREE_ELECTIVE (student major MATH). A-101 grade B+ (3.3), B-101 grade B- (2.7)."""
        partner = fixtures.create_partner(name="GPA College", code="GP", credit_system="SEMESTER")
        ca = fixtures.create_course(code="HIST-210", title="History A", credit_hours=2.5, department="HIST")
        cb = fixtures.create_course(code="HIST-211", title="History B", credit_hours=1.5, department="HIST")
        agreement = fixtures.create_agreement(partner["id"])
        fixtures.activate_agreement(agreement["id"])
        fixtures.add_equivalency(agreement["id"], ca["id"], "A-101", external_credit_hours=2.5)
        fixtures.add_equivalency(agreement["id"], cb["id"], "B-101", external_credit_hours=1.5)
        student = fixtures.create_student(major="MATH")
        transcript = fixtures.create_verified_transcript(
            student["id"], partner["id"],
            courses=[
                create_transcript_course_payload(external_course_code="A-101", title="HA", credit_hours=2.5, grade="B+"),
                create_transcript_course_payload(external_course_code="B-101", title="HB", credit_hours=1.5, grade="B-"),
            ],
        )
        evaluation = fixtures.create_evaluation(student["id"], transcript["id"])
        lines = fixtures.get_evaluation_lines(evaluation["id"])
        fixtures.get_success_data(api_client.start_evaluation_review(evaluation["id"], EVALUATOR))
        fixtures.adopt_all_lines(evaluation["id"], lines)
        fixtures.finalize_evaluation(evaluation["id"], EVAL_A)
        fixtures.post_evaluation(evaluation["id"], EVAL_B)
        return student

    def test_transfer_gpa_uses_per_line_first_rounding(self):
        """PRD §3.8: "each line contributes quality points equal to its
        `grade_points` times its `awarded_credits`, rounded half-up to two decimal
        places **before** any summation; the rounded products are summed and divided
        by the total awarded credits; the quotient is rounded half-up to three
        decimal places".

        Design: Corner/calculations/transfer_gpa_per_line_rounding_precision
        """
        student = self._setup_posted_two_lines()
        progress = get_success_data(
            api_client.get_degree_progress(student["id"], EVALUATOR, params={"variant": "CERTIFIED"})
        )
        # qp: round(3.3*2.5,2)=8.25; round(2.7*1.5,2)=4.05; (8.25+4.05)/4.0 = 3.075
        assert progress["transfer_gpa"] == pytest.approx(3.075, abs=1e-9)
        assert progress["total_applied_credits"] == pytest.approx(4.0, abs=1e-9)
