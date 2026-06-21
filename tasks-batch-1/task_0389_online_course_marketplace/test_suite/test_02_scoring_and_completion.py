"""Quiz scoring, the weighted completion gate, progress tracking, and the divergent
completion fork (PRD §3.7, §3.8).

Queue A: dual_variant_calc (weighted gate vs simple average), boundary_precision_check
(inclusive passing-score), non_linear_state_machine (COMPLETED vs REFUNDED fork).
Queue B: non-graded scoring, progress fraction, certificate visibility.
"""
import pytest

from test_helpers import (
    validate_success,
    assert_certificate,
    set_clock,
    create_instructor,
    create_learner,
    create_published_course,
    create_published_graded_course,
    enroll_in_course,
    complete_lesson,
    make_learner_headers,
    make_instructor_headers,
    create_lesson_completion_payload,
)


# ===========================================================================
# Queue A — dual_variant_calc / course_score_weighted_vs_simple_average_diverge
# ===========================================================================
def _setup_graded_three_lesson_enrollment():
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, lessons = create_published_graded_course(
        instructor["id"],
        graded_lessons=[
            {"is_graded": True, "quiz_weight": 3, "question_count": 10},
            {"is_graded": True, "quiz_weight": 1, "question_count": 10},
            {"is_graded": True, "quiz_weight": 1, "question_count": 5},
        ],
        list_price_cents=0, passing_score_pct=0.70, completion_threshold_pct=0.60,
    )
    enrollment = enroll_in_course(learner["id"], course["id"])
    # L1 9/10=0.9 (passed), L2 6/10=0.6 (not passed), L3 5/5=1.0 (passed).
    # 2 of 3 lessons passed -> progress_pct 0.67 >= completion_threshold 0.60, and the
    # weighted_score 0.86 >= passing 0.70, so the enrollment auto-completes and issues a
    # certificate whose final_score_pct snapshots the weighted 0.86 (PRD §3.7, §3.8).
    complete_lesson(learner["id"], enrollment["id"], lessons[0]["id"], correct_answers=9)
    complete_lesson(learner["id"], enrollment["id"], lessons[1]["id"], correct_answers=6)
    complete_lesson(learner["id"], enrollment["id"], lessons[2]["id"], correct_answers=5)
    return instructor, learner, course, lessons, enrollment


def test_weighted_score_uses_fixed_total_weight_denominator(api):
    """PRD §3.7: "The numerator is the sum, over those graded lessons that have a
    completion on this enrollment, of each completion's `score_pct` multiplied by its
    lesson's `quiz_weight`. The weighted score is the numerator divided by the fixed
    total weight, rounded to four decimal places."

    weights 3/1/1 (total 5), scores 0.9/0.6/1.0 -> (0.9*3+0.6*1+1.0*1)/5 = 4.3/5 = 0.86.

    Design: Difficulty/dual_variant_calc/course_score_weighted_vs_simple_average_diverge
    """
    instructor, learner, course, lessons, enrollment = _setup_graded_three_lesson_enrollment()
    res = api.get_enrollment(enrollment["id"], make_learner_headers(learner["id"]))
    refreshed = validate_success(res, 200)
    assert refreshed["weighted_score_pct"] == pytest.approx(0.86, abs=1e-9), (
        f"weighted gate (4.3/5)==0.86, got {refreshed['weighted_score_pct']}"
    )


def test_certificate_final_score_snapshots_weighted_not_simple_average(api):
    """PRD §3.8: "a `final_score_pct` snapshot of the enrollment's `weighted_score_pct`
    (to four decimal places) at issuance".

    The certificate's final_score_pct is the weighted 0.86, which diverges from the
    simple unweighted average (0.9+0.6+1.0)/3 == 0.8333 for the identical data.

    Design: Difficulty/dual_variant_calc/course_score_weighted_vs_simple_average_diverge
    """
    instructor, learner, course, lessons, enrollment = _setup_graded_three_lesson_enrollment()
    res = api.get_enrollment_certificate(enrollment["id"], make_learner_headers(learner["id"]))
    certs = validate_success(res, 200)
    assert isinstance(certs, list) and len(certs) == 1, "exactly one certificate issued"
    assert_certificate(certs[0])
    assert certs[0]["final_score_pct"] == pytest.approx(0.86, abs=1e-9), (
        f"final_score_pct snapshots weighted 0.86, got {certs[0]['final_score_pct']}"
    )
    assert certs[0]["final_score_pct"] != pytest.approx(0.8333, abs=1e-4), (
        "weighted gate must diverge from the simple-average transcript (0.8333)"
    )


# ===========================================================================
# Queue A — boundary_precision_check / passing_score_inclusive_ge_boundary_on_lesson_completion
# ===========================================================================
def test_passing_score_exactly_at_threshold_passes(api):
    """PRD §3.7: "the lesson is `passed` when that `score_pct` is at least the course's
    `passing_score_pct` — the comparison is inclusive, so a score exactly equal to the
    passing threshold passes."

    passing_score_pct 0.70, question_count 10, correct_answers 7 -> score 0.70 -> passed.

    Design: Difficulty/boundary_precision_check/passing_score_inclusive_ge_boundary_on_lesson_completion
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, lessons = create_published_graded_course(
        instructor["id"],
        graded_lessons=[{"is_graded": True, "quiz_weight": 1, "question_count": 10}],
        list_price_cents=0, passing_score_pct=0.70, completion_threshold_pct=1.00,
    )
    enrollment = enroll_in_course(learner["id"], course["id"])
    res = api.create_lesson_completion(
        create_lesson_completion_payload(enrollment["id"], lessons[0]["id"], correct_answers=7),
        make_learner_headers(learner["id"]),
    )
    completion = validate_success(res, 201)
    assert completion["score_pct"] == pytest.approx(0.70, abs=1e-9), (
        f"7/10 == 0.70, got {completion['score_pct']}"
    )
    assert completion["passed"] is True, "score exactly at threshold passes (inclusive >=)"


def test_passing_score_just_below_threshold_fails(api):
    """PRD §3.7: "the lesson is `passed` when that `score_pct` is at least the course's
    `passing_score_pct`".

    passing_score_pct 0.70, question_count 10, correct_answers 6 -> score 0.60 -> not passed.

    Design: Difficulty/boundary_precision_check/passing_score_inclusive_ge_boundary_on_lesson_completion
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, lessons = create_published_graded_course(
        instructor["id"],
        graded_lessons=[{"is_graded": True, "quiz_weight": 1, "question_count": 10}],
        list_price_cents=0, passing_score_pct=0.70, completion_threshold_pct=1.00,
    )
    enrollment = enroll_in_course(learner["id"], course["id"])
    res = api.create_lesson_completion(
        create_lesson_completion_payload(enrollment["id"], lessons[0]["id"], correct_answers=6),
        make_learner_headers(learner["id"]),
    )
    completion = validate_success(res, 201)
    assert completion["score_pct"] == pytest.approx(0.60, abs=1e-9), (
        f"6/10 == 0.60, got {completion['score_pct']}"
    )
    assert completion["passed"] is False, "0.60 < 0.70 does not pass"


# ===========================================================================
# Queue A — non_linear_state_machine / enrollment_branch_fork_completed_vs_refunded
# ===========================================================================
def test_completed_branch_issues_certificate_and_no_wallet_credit(api):
    """PRD §3.8: "On completion, the system sets the enrollment's `ceu_awarded` to the
    course's `ceu_credits` and issues exactly one `Certificate` for the enrollment.
    Completion moves no money — the originating `SALE` ledger entry is left untouched."

    A learner who finishes a single-lesson non-graded course reaches COMPLETED with a
    certificate and an unchanged wallet (no refund credit).

    Design: Difficulty/non_linear_state_machine/enrollment_branch_fork_completed_vs_refunded
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, lesson = create_published_course(
        instructor["id"], list_price_cents=1000, completion_threshold_pct=1.00
    )
    enrollment = enroll_in_course(learner["id"], course["id"])
    complete_lesson(learner["id"], enrollment["id"], lesson["id"])
    refreshed = validate_success(
        api.get_enrollment(enrollment["id"], make_learner_headers(learner["id"])), 200
    )
    assert refreshed["status"] == "COMPLETED"
    certs = validate_success(
        api.get_enrollment_certificate(enrollment["id"], make_learner_headers(learner["id"])), 200
    )
    assert len(certs) == 1, "COMPLETED branch issues exactly one certificate"
    learner_after = validate_success(
        api.get_learner(learner["id"], make_learner_headers(learner["id"])), 200
    )
    assert learner_after["wallet_credit_cents"] == 0, (
        "COMPLETED branch credits no wallet (that is the REFUNDED branch)"
    )


def test_refunded_branch_credits_wallet_and_issues_no_certificate(api):
    """PRD §3.9: "A successful refund unwinds the purchase across four resources at once.
    The learner's `wallet_credit_cents` is increased by the enrollment's
    `gross_price_cents`."

    A learner who self-refunds a 4000c enrollment reaches REFUNDED with wallet 4000 and
    no certificate (the divergent branch from COMPLETED).

    Design: Difficulty/non_linear_state_machine/enrollment_branch_fork_completed_vs_refunded
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, _ = create_published_course(
        instructor["id"], list_price_cents=4000, refund_window_days=30
    )
    enrollment = enroll_in_course(learner["id"], course["id"])
    refunded = validate_success(
        api.refund_enrollment(enrollment["id"], make_learner_headers(learner["id"])), 200
    )
    assert refunded["status"] == "REFUNDED"
    learner_after = validate_success(
        api.get_learner(learner["id"], make_learner_headers(learner["id"])), 200
    )
    assert learner_after["wallet_credit_cents"] == 4000, (
        f"REFUNDED branch credits wallet by gross 4000, got {learner_after['wallet_credit_cents']}"
    )
    certs = validate_success(
        api.get_enrollment_certificate(enrollment["id"], make_learner_headers(learner["id"])), 200
    )
    assert len(certs) == 0, "REFUNDED branch issues no certificate"


# ===========================================================================
# Queue B — calculations / lesson_completion_nongraded_scores_full
# ===========================================================================
def test_nongraded_lesson_completion_scores_full(api):
    """PRD §3.7: "For a non-graded lesson the `score_pct` is fixed at 1.0 and the lesson
    is `passed`."

    Completing a non-graded lesson sets score_pct 1.0 and passed true.

    Design: Corner/calculations/lesson_completion_nongraded_scores_full
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, lesson = create_published_course(
        instructor["id"], list_price_cents=0, completion_threshold_pct=1.00,
        lesson_overrides={"is_graded": False},
    )
    enrollment = enroll_in_course(learner["id"], course["id"])
    res = api.create_lesson_completion(
        create_lesson_completion_payload(enrollment["id"], lesson["id"]),
        make_learner_headers(learner["id"]),
    )
    completion = validate_success(res, 201)
    assert completion["score_pct"] == pytest.approx(1.0, abs=1e-9)
    assert completion["passed"] is True


# ===========================================================================
# Queue B — calculations / progress_pct_two_of_three_lessons
# ===========================================================================
def test_progress_pct_two_of_three_published_lessons(api):
    """PRD §3.7: "`progress_pct` is that count divided by the course's
    `published_lesson_count`, rounded to two decimal places."

    Completing 2 of 3 published lessons yields progress_pct 0.67 and the enrollment
    stays ACTIVE (threshold 1.00 not met).

    Design: Corner/calculations/progress_pct_two_of_three_lessons
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, lessons = create_published_graded_course(
        instructor["id"],
        graded_lessons=[{"is_graded": False}, {"is_graded": False}, {"is_graded": False}],
        list_price_cents=0, completion_threshold_pct=1.00,
    )
    enrollment = enroll_in_course(learner["id"], course["id"])
    complete_lesson(learner["id"], enrollment["id"], lessons[0]["id"])
    complete_lesson(learner["id"], enrollment["id"], lessons[1]["id"])
    refreshed = validate_success(
        api.get_enrollment(enrollment["id"], make_learner_headers(learner["id"])), 200
    )
    assert refreshed["progress_pct"] == pytest.approx(0.67, abs=1e-9), (
        f"2/3 rounded 2dp == 0.67, got {refreshed['progress_pct']}"
    )
    assert refreshed["status"] == "ACTIVE", "threshold 1.00 not yet met"


# ===========================================================================
# Queue B — consistency_model / completion_certificate_visible_same_session
# ===========================================================================
def test_certificate_visible_immediately_after_completion(api):
    """PRD §3.8: "On completion, the system sets the enrollment's `ceu_awarded` to the
    course's `ceu_credits` and issues exactly one `Certificate` for the enrollment."

    Right after the completing lesson-completion, GET the certificate returns one row
    with ceu_credits 1.5 and the enrollment is COMPLETED with ceu_awarded 1.5.

    Design: Corner/consistency_model/completion_certificate_visible_same_session
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, lesson = create_published_course(
        instructor["id"], list_price_cents=0, ceu_credits=1.5, completion_threshold_pct=1.00
    )
    enrollment = enroll_in_course(learner["id"], course["id"])
    complete_lesson(learner["id"], enrollment["id"], lesson["id"])
    certs = validate_success(
        api.get_enrollment_certificate(enrollment["id"], make_learner_headers(learner["id"])), 200
    )
    assert len(certs) == 1, "certificate retrievable immediately after completion"
    assert certs[0]["ceu_credits"] == pytest.approx(1.5, abs=1e-9)
    refreshed = validate_success(
        api.get_enrollment(enrollment["id"], make_learner_headers(learner["id"])), 200
    )
    assert refreshed["status"] == "COMPLETED"
    assert refreshed["ceu_awarded"] == pytest.approx(1.5, abs=1e-9)
