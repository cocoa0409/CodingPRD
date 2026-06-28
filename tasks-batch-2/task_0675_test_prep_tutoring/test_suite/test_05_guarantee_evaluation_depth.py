"""Depth tests for the score-improvement guarantee evaluation and practice scoring.

Covers difficulty rules: dual_variant_calc, combinatorial_formula,
boundary_precision_check, and the GuaranteeClaim->Enrollment cross-entity dependency.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, make_student_headers, make_instructor_headers, TEST_USERS,
    setup_concluded_enrollment_with_scores, setup_active_enrollment,
    score_attempt, file_and_review_claim,
)

REGISTRAR = TEST_USERS["registrar_headers"]


class TestDualVariantGuaranteeProjection:
    def test_final_best_differs_from_provisional_latest(self, api):
        """PRD §3.5: "its best_practice_score is recomputed as the maximum
        scaled_score over those completed practice attempts (null if there are none)."
        PRD §3.5: "the analytics projection instead uses the most recent completed
        practice attempt's scaled_score — the latest, not the best — projected against
        the student's diagnostic_score."

        Two PRACTICE attempts scored 1150 then 1050: best=1150 (final) but latest=1050
        (provisional), so the two improvement figures diverge.

        Design: Difficulty/dual_variant_calc/guarantee_eligibility_final_best_vs_provisional_latest
        """
        base = setup_active_enrollment(
            fmt="SELF", guarantee_min_delta=200, required_practice_tests=1,
            required_attendance_pct=0.0, list_price_cents=120000,
            student_email="dv1@x.com")
        enr_id = base["enrollment"]["id"]
        inst_id = base["instructor"]["id"]
        stu_id = base["student"]["id"]

        score_attempt(enr_id, inst_id, "DIAGNOSTIC", 50, 80, stu_id)   # -> 1000
        score_attempt(enr_id, inst_id, "PRACTICE", 575, 800, stu_id)   # -> 1150 (best)
        score_attempt(enr_id, inst_id, "PRACTICE", 525, 800, stu_id)   # -> 1050 (latest)

        data = validate_success(
            api.get_enrollment_analytics(enr_id, make_student_headers(stu_id)))
        assert data["best_practice_score"] == 1150, (
            f"best over completed practice must be 1150, got {data['best_practice_score']}")
        student = validate_success(api.get_student(stu_id, REGISTRAR))
        assert student["diagnostic_score"] == 1000
        # Final improvement (best-based) = 150; provisional (latest-based) = 50; they differ.
        assert (1150 - 1000) != (1050 - 1000)

    def test_diagnostic_score_captured_as_baseline(self, api):
        """PRD §3.5: "If the attempt is a DIAGNOSTIC and the student's diagnostic_score
        is still null, the student's diagnostic_score is set to the just-computed
        scaled_score (this is how the baseline is captured for the guarantee)."

        Design: Difficulty/dual_variant_calc/guarantee_eligibility_final_best_vs_provisional_latest
        """
        base = setup_active_enrollment(fmt="SELF", student_email="dv1b@x.com")
        enr_id = base["enrollment"]["id"]
        inst_id = base["instructor"]["id"]
        stu_id = base["student"]["id"]
        diag = score_attempt(enr_id, inst_id, "DIAGNOSTIC", 50, 80, stu_id)
        assert diag["scaled_score"] == 1000
        student = validate_success(api.get_student(stu_id, REGISTRAR))
        assert student["diagnostic_score"] == 1000


class TestDualVariantRefund:
    def test_financed_refund_equals_amount_collected(self, api):
        """PRD §3.7: "when an installment plan exists it equals that plan's
        amount_paid_cents (which may be less than price_paid_cents if installments remain)".
        PRD §3.7: "On a REFUND resolution, the claim's refund_amount_cents is set to the
        conserved refund amount, the enrollment's guarantee_status becomes REFUND_ISSUED,
        and the enrollment's OPEN installment plan (if any) cascades from OPEN to REFUNDED."

        EARLYBIRD price 102000, financed over 2 installments with one 51000 payment ->
        refund 51000 and plan REFUNDED.

        Design: Difficulty/dual_variant_calc/guarantee_refund_financed_vs_paid_up_front
        """
        base = setup_concluded_enrollment_with_scores(
            fmt="SELF", guarantee_min_delta=200, required_attendance_pct=0.0,
            required_practice_tests=1, list_price_cents=120000, coupon_code="EARLYBIRD",
            num_installments=2, first_payment_cents=51000,
            diagnostic_raw=50, diagnostic_total=80, practice_specs=((550, 800),),
            student_email="dvr@x.com")
        enr_id = base["enrollment"]["id"]
        stu_id = base["student"]["id"]
        plan_id = base["plan"]["id"]

        assert base["enrollment"]["price_paid_cents"] == 102000
        assert base["enrollment"]["guarantee_status"] == "ELIGIBLE"

        claim = file_and_review_claim(enr_id, stu_id, "REFUND")
        approved = validate_success(api.approve_guarantee_claim(claim["id"], REGISTRAR))
        assert approved["refund_amount_cents"] == 51000
        plan = validate_success(api.get_installment_plan(plan_id, REGISTRAR))
        assert plan["status"] == "REFUNDED"

    def test_refund_marks_enrollment_refund_issued(self, api):
        """PRD §3.7: "the enrollment's guarantee_status becomes REFUND_ISSUED".

        Design: Difficulty/dual_variant_calc/guarantee_refund_financed_vs_paid_up_front
        """
        base = setup_concluded_enrollment_with_scores(
            fmt="SELF", guarantee_min_delta=200, required_attendance_pct=0.0,
            required_practice_tests=1, list_price_cents=120000, coupon_code="EARLYBIRD",
            num_installments=2, first_payment_cents=51000,
            diagnostic_raw=50, diagnostic_total=80, practice_specs=((550, 800),),
            student_email="dvr2@x.com")
        enr_id = base["enrollment"]["id"]
        stu_id = base["student"]["id"]
        claim = file_and_review_claim(enr_id, stu_id, "REFUND")
        validate_success(api.approve_guarantee_claim(claim["id"], REGISTRAR))
        enrollment = validate_success(api.get_enrollment(enr_id, REGISTRAR))
        assert enrollment["guarantee_status"] == "REFUND_ISSUED"


class TestScaledScoreRounding:
    def test_product_rounded_once_not_ratio_first(self, api):
        """PRD §3.5: "multiply that ratio by the course's baseline_scale_max, and round
        the single resulting product half up to a whole number of points — this is the
        scaled_score. It is essential to round only once at the end".

        raw 1/16 on SAT 1600: round(0.0625*1600)=100, not round(0.06)*1600.

        Design: Difficulty/combinatorial_formula/scaled_score_rounds_product_once_not_ratio_first
        """
        base = setup_active_enrollment(fmt="SELF", student_email="rnd@x.com")
        enr_id = base["enrollment"]["id"]
        inst_id = base["instructor"]["id"]
        stu_id = base["student"]["id"]
        att = get_success_data(api.create_practice_attempt(
            {"enrollment_id": enr_id, "attempt_type": "PRACTICE", "raw_correct": 1,
             "total_items": 16}, make_student_headers(stu_id)))
        scored = validate_success(
            api.score_practice_attempt(att["id"], make_instructor_headers(inst_id)))
        assert scored["scaled_score"] == 100
        assert scored["status"] == "COMPLETED"

    def test_scaled_score_completes_attempt(self, api):
        """PRD §3.5: "Scoring an attempt is an instructor-only action that advances
        STARTED to COMPLETED."

        Design: Difficulty/combinatorial_formula/scaled_score_rounds_product_once_not_ratio_first
        """
        base = setup_active_enrollment(fmt="SELF", student_email="rnd2@x.com")
        scored = score_attempt(
            base["enrollment"]["id"], base["instructor"]["id"], "PRACTICE", 1, 16,
            base["student"]["id"])
        assert scored["status"] == "COMPLETED"
        assert scored["scaled_score"] == 100


class TestThreeInputGuaranteeGate:
    def test_attendance_shortfall_makes_ineligible(self, api):
        """PRD §3.7: "the attendance fraction — the enrollment's sessions_attended divided
        by the cohort's total_sessions — must be at least the course's required_attendance_pct
        (the boundary value itself counts as satisfied)."
        PRD §3.7: "When all prerequisites hold and the guarantee was missed, the enrollment's
        guarantee_status is set to ELIGIBLE; otherwise it is set to INELIGIBLE."

        LIVE course, attendance 3/4=0.75 < required 0.80 -> INELIGIBLE despite delta 100<200.

        Design: Difficulty/combinatorial_formula/guarantee_eligibility_three_input_nonlinear_gate
        """
        base = setup_concluded_enrollment_with_scores(
            fmt="LIVE", guarantee_min_delta=200, required_attendance_pct=0.80,
            required_practice_tests=1, total_sessions=4, sessions_attended=3,
            diagnostic_raw=50, diagnostic_total=80, practice_specs=((550, 800),),
            student_email="gate@x.com")
        enr = base["enrollment"]
        assert enr["guarantee_status"] == "INELIGIBLE"
        assert enr["status"] == "COMPLETED"

    def test_completed_enrollment_after_conclude(self, api):
        """PRD §3.2: "every enrollment on the cohort that is currently ACTIVE is
        transitioned to COMPLETED — and each such completion evaluates the student's
        guarantee eligibility as described in §3.7".

        Design: Difficulty/combinatorial_formula/guarantee_eligibility_three_input_nonlinear_gate
        """
        base = setup_concluded_enrollment_with_scores(
            fmt="LIVE", guarantee_min_delta=200, required_attendance_pct=0.80,
            required_practice_tests=1, total_sessions=4, sessions_attended=3,
            diagnostic_raw=50, diagnostic_total=80, practice_specs=((550, 800),),
            student_email="gate2@x.com")
        assert base["enrollment"]["status"] == "COMPLETED"
        assert base["cohort"]["status"] == "CONCLUDED"


class TestGuaranteeDeltaBoundary:
    def test_delta_exactly_meeting_min_is_ineligible(self, api):
        """PRD §3.7: "the guarantee is considered missed only when that improvement is
        strictly less than guarantee_min_delta, so a student who meets the promised delta
        exactly has not missed it."

        diag 1000, best 1200 -> delta exactly 200 == min 200 -> INELIGIBLE.

        Design: Difficulty/boundary_precision_check/guarantee_delta_exactly_meets_min_is_not_eligible
        """
        base = setup_concluded_enrollment_with_scores(
            fmt="SELF", guarantee_min_delta=200, required_attendance_pct=0.0,
            required_practice_tests=1, diagnostic_raw=50, diagnostic_total=80,
            practice_specs=((600, 800),), student_email="bd1@x.com")  # 600/800=0.75*1600=1200
        enr = base["enrollment"]
        student = validate_success(api.get_student(base["student"]["id"], REGISTRAR))
        assert student["diagnostic_score"] == 1000
        assert enr["best_practice_score"] == 1200
        assert enr["guarantee_status"] == "INELIGIBLE"

    def test_best_practice_score_reflects_delta_at_boundary(self, api):
        """PRD §3.5: "its best_practice_score is recomputed as the maximum scaled_score over
        those completed practice attempts (null if there are none)."
        PRD §3.7: "The guarantee-miss test then compares the realized improvement — the
        enrollment's best_practice_score minus the student's diagnostic_score — against the
        course's guarantee_min_delta".

        best 1200, diagnostic 1000: realized improvement is exactly the min delta 200.

        Design: Difficulty/boundary_precision_check/guarantee_delta_exactly_meets_min_is_not_eligible
        """
        base = setup_concluded_enrollment_with_scores(
            fmt="SELF", guarantee_min_delta=200, required_attendance_pct=0.0,
            required_practice_tests=1, diagnostic_raw=50, diagnostic_total=80,
            practice_specs=((600, 800),), student_email="bd1b@x.com")
        enr = base["enrollment"]
        student = validate_success(api.get_student(base["student"]["id"], REGISTRAR))
        assert enr["best_practice_score"] - student["diagnostic_score"] == 200
        assert enr["guarantee_status"] == "INELIGIBLE"

    def test_zero_completed_practice_tests_fails_prereq(self, api):
        """PRD §3.7: "the enrollment's completed_practice_count must be at least the
        course's required_practice_tests."
        PRD §3.5: "its best_practice_score is recomputed as the maximum scaled_score over
        those completed practice attempts (null if there are none)."

        Scored diagnostic but ZERO completed PRACTICE -> practice prereq fails -> INELIGIBLE.

        Design: Difficulty/boundary_precision_check/zero_completed_practice_tests_fails_prereq
        """
        base = setup_concluded_enrollment_with_scores(
            fmt="SELF", guarantee_min_delta=200, required_attendance_pct=0.0,
            required_practice_tests=1, diagnostic_raw=50, diagnostic_total=80,
            practice_specs=(), student_email="bd2@x.com")
        enr = base["enrollment"]
        assert enr["completed_practice_count"] == 0
        assert enr["best_practice_score"] is None
        assert enr["guarantee_status"] == "INELIGIBLE"

    def test_zero_practice_completes_enrollment_anyway(self, api):
        """PRD §3.2: "every enrollment on the cohort that is currently ACTIVE is transitioned
        to COMPLETED — and each such completion evaluates the student's guarantee eligibility
        as described in §3.7".
        PRD §3.5: "its best_practice_score is recomputed as the maximum scaled_score over
        those completed practice attempts (null if there are none)."

        With zero completed PRACTICE attempts the enrollment still COMPLETEs on conclude;
        best_practice_score stays null.

        Design: Difficulty/boundary_precision_check/zero_completed_practice_tests_fails_prereq
        """
        base = setup_concluded_enrollment_with_scores(
            fmt="SELF", guarantee_min_delta=200, required_attendance_pct=0.0,
            required_practice_tests=1, diagnostic_raw=50, diagnostic_total=80,
            practice_specs=(), student_email="bd2b@x.com")
        enr = base["enrollment"]
        assert enr["status"] == "COMPLETED"
        assert enr["best_practice_score"] is None


class TestClaimReviewRequiresEligible:
    def test_review_rejected_when_enrollment_ineligible(self, api):
        """PRD §3.7: "the parent enrollment's guarantee_status must be ELIGIBLE, or the
        request is rejected with ERR_GUARANTEE_NOT_ELIGIBLE."

        Enrollment INELIGIBLE (delta met exactly) -> filing then reviewing rejected.

        Design: Difficulty/cross_entity_state_dependency/claim_review_requires_enrollment_eligible
        """
        base = setup_concluded_enrollment_with_scores(
            fmt="SELF", guarantee_min_delta=200, required_attendance_pct=0.0,
            required_practice_tests=1, diagnostic_raw=50, diagnostic_total=80,
            practice_specs=((600, 800),), student_email="ce@x.com")  # delta exactly 200
        enr_id = base["enrollment"]["id"]
        stu_id = base["student"]["id"]
        assert base["enrollment"]["guarantee_status"] == "INELIGIBLE"
        claim = get_success_data(api.create_guarantee_claim(
            {"enrollment_id": enr_id, "resolution": "REFUND"}, make_student_headers(stu_id)))
        resp = api.review_guarantee_claim(claim["id"], REGISTRAR)
        validate_error(resp, ApiErrorId.ERR_GUARANTEE_NOT_ELIGIBLE)
        unchanged = validate_success(api.get_guarantee_claim(claim["id"], REGISTRAR))
        assert unchanged["status"] == "FILED"

    def test_ineligible_enrollment_state_unchanged_by_failed_review(self, api):
        """PRD §3.7: "the parent enrollment's guarantee_status must be ELIGIBLE, or the
        request is rejected with ERR_GUARANTEE_NOT_ELIGIBLE."

        Design: Difficulty/cross_entity_state_dependency/claim_review_requires_enrollment_eligible
        """
        base = setup_concluded_enrollment_with_scores(
            fmt="SELF", guarantee_min_delta=200, required_attendance_pct=0.0,
            required_practice_tests=1, diagnostic_raw=50, diagnostic_total=80,
            practice_specs=((600, 800),), student_email="ce2@x.com")
        enr_id = base["enrollment"]["id"]
        stu_id = base["student"]["id"]
        claim = get_success_data(api.create_guarantee_claim(
            {"enrollment_id": enr_id, "resolution": "REFUND"}, make_student_headers(stu_id)))
        api.review_guarantee_claim(claim["id"], REGISTRAR)
        enr = validate_success(api.get_enrollment(enr_id, REGISTRAR))
        assert enr["guarantee_status"] == "INELIGIBLE"
