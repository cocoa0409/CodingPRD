"""Progress vs mastery, the two Enrollment axes, certification, quizzes, and drip locks."""
from test_helpers import (
    ApiErrorId, validate_success, validate_error,
    make_creator_headers, make_student_headers,
    fixtures as fx,
)


# --------------------------------------------------------------------------
# Difficulty: raw_progress (provisional) vs is_mastery_complete (final) diverge.
# --------------------------------------------------------------------------

def test_raw_progress_100_but_mastery_false_when_quiz_unpassed(api):
    """PRD §3.6: "A learner can therefore reach 100 percent `raw_progress_pct` yet remain
    short of mastery if a required quiz is still unpassed."

    Design: Difficulty/dual_variant_calc/enrollment_progress_vs_mastery
    """
    ctx = fx.setup_paid_enrollment(
        lesson_overrides={"is_quiz_required": True, "quiz_passing_score": 70})
    enr = fx.complete_lesson(ctx["enrollment"]["id"], ctx["lesson"]["id"], ctx["student"]["id"])
    assert enr["raw_progress_pct"] == 100
    assert enr["is_mastery_complete"] is False


def test_access_stays_active_without_mastery(api):
    """PRD §3.6: "An enrollment's `is_mastery_complete` becomes true only when its completed
    lesson count equals the course's `published_lesson_count` and, in addition, every
    published lesson whose `is_quiz_required` is true has at least one quiz attempt for this
    enrollment with `passed` true."

    Design: Difficulty/dual_variant_calc/enrollment_progress_vs_mastery
    """
    ctx = fx.setup_paid_enrollment(
        lesson_overrides={"is_quiz_required": True, "quiz_passing_score": 70})
    enr = fx.complete_lesson(ctx["enrollment"]["id"], ctx["lesson"]["id"], ctx["student"]["id"])
    assert enr["access_status"] == "ACTIVE"


def test_billing_axis_unaffected_by_completion(api):
    """PRD §2.8: "The two axes advance on their own triggers but are coupled at key moments
    — paying the initial invoice advances both, and a refund or cancellation drives both to
    their terminal reversal states together."

    Design: Difficulty/non_linear_state_machine/enrollment_parallel_access_and_billing_axes
    """
    ctx = fx.setup_paid_enrollment(
        lesson_overrides={"is_quiz_required": True, "quiz_passing_score": 70})
    fx.complete_lesson(ctx["enrollment"]["id"], ctx["lesson"]["id"], ctx["student"]["id"])
    fx.submit_quiz(ctx["enrollment"]["id"], ctx["lesson"]["id"], 80, ctx["student"]["id"])
    enr = validate_success(
        api.get_enrollment(ctx["enrollment"]["id"], make_student_headers(ctx["student"]["id"])))
    assert enr["billing_status"] == "CURRENT"


# --------------------------------------------------------------------------
# Difficulty: completing the last lesson mints a certificate and bubbles completion_count.
# --------------------------------------------------------------------------

def test_completion_mints_certificate(api):
    """PRD §3.6: "When completing a lesson makes mastery newly true, the enrollment's
    `access_status` moves `ACTIVE → COMPLETED`, a certificate is minted by setting
    `certificate_serial` and stamping `certificate_issued_at` with the current clock, and
    the course's `completion_count` is incremented."

    Design: Difficulty/transitive_cascade/complete_lesson_depth2_certificate_cascade
    """
    ctx = fx.setup_paid_enrollment(lesson_overrides={"is_quiz_required": False})
    enr = fx.complete_lesson(ctx["enrollment"]["id"], ctx["lesson"]["id"], ctx["student"]["id"])
    assert enr["access_status"] == "COMPLETED"
    assert enr["certificate_serial"] is not None


def test_completion_bubbles_course_completion_count(api):
    """PRD §3.6: "The course's `completion_count` counts enrollments in `access_status`
    `COMPLETED`; its `enrollment_count` counts enrollments whose billing is neither
    `CANCELLED` nor `REFUNDED`."

    Design: Difficulty/transitive_cascade/complete_lesson_depth2_certificate_cascade
    """
    ctx = fx.setup_paid_enrollment(lesson_overrides={"is_quiz_required": False})
    fx.complete_lesson(ctx["enrollment"]["id"], ctx["lesson"]["id"], ctx["student"]["id"])
    course = validate_success(
        api.get_course(ctx["course"]["id"], make_creator_headers(ctx["creator"]["id"])))
    assert course["completion_count"] == 1


# --------------------------------------------------------------------------
# Corner: quizzes and drip locks.
# --------------------------------------------------------------------------

def test_quiz_score_equal_to_threshold_passes(api):
    """PRD §3.6: "the attempt records `passed` as true exactly when the score is at or
    above that lesson's `quiz_passing_score` (the boundary is inclusive)."

    Design: Corner/calculations/quiz_attempt_passed_inclusive_boundary
    """
    ctx = fx.setup_paid_enrollment(
        lesson_overrides={"is_quiz_required": True, "quiz_passing_score": 70})
    resp = api.create_quiz_attempt(
        ctx["enrollment"]["id"], {"lesson_id": ctx["lesson"]["id"], "score": 70},
        make_student_headers(ctx["student"]["id"]))
    data = validate_success(resp, expected_status=201)
    assert data["passed"] is True


def test_quiz_attempt_on_non_quiz_lesson_rejected(api):
    """PRD §3.6: "A quiz attempt may only be submitted for a lesson whose `is_quiz_required`
    is true, else `ERR_QUIZ_NOT_REQUIRED`, and the same course-match and published-lesson
    rules apply as for completion."

    Design: Corner/errors/quiz_attempt_on_non_quiz_lesson_returns_422
    """
    ctx = fx.setup_paid_enrollment(lesson_overrides={"is_quiz_required": False})
    resp = api.create_quiz_attempt(
        ctx["enrollment"]["id"], {"lesson_id": ctx["lesson"]["id"], "score": 90},
        make_student_headers(ctx["student"]["id"]))
    validate_error(resp, ApiErrorId.ERR_QUIZ_NOT_REQUIRED.value)


def test_complete_drip_locked_lesson_rejected(api):
    """PRD §3.6: "if the current clock is earlier than `activated_at` plus the lesson's
    `drip_offset_days`, it is still locked and the request is rejected with
    `ERR_LESSON_LOCKED`."

    Design: Corner/validations/lesson_drip_locked_returns_409
    """
    # Enrollment activates at the clock default 2026-03-01; lesson unlocks 30 days later.
    ctx = fx.setup_paid_enrollment(lesson_overrides={"drip_offset_days": 30})
    resp = api.complete_lesson(
        ctx["enrollment"]["id"], {"lesson_id": ctx["lesson"]["id"]},
        make_student_headers(ctx["student"]["id"]))
    validate_error(resp, ApiErrorId.ERR_LESSON_LOCKED.value)
