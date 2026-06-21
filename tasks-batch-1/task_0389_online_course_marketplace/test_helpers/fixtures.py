"""Composite setup helpers for multi-step test prerequisites (PRD §3).

Uses get_success_data() (lenient validator) so a broken precondition surfaces as a
clear "Setup step failed" error rather than a confusing assertion failure.

Every helper builds its state from scratch through PRD-declared endpoints only — the
test harness restarts the server (empty DB) before every test, so nothing is carried
over. Identity threading is mandatory (PRD §2.1): after a fixture creates an Instructor
or Learner it threads the real id into make_instructor_headers()/make_learner_headers()
for every ownership-gated call.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_instructor_payload,
    create_learner_payload,
    create_course_payload,
    create_lesson_payload,
    create_coupon_payload,
    create_bundle_payload,
    enroll_bundle_payload,
    enroll_course_payload,
    create_lesson_completion_payload,
    create_review_payload,
    create_payout_payload,
    approve_payout_payload,
    clock_payload,
)
from .test_users import (
    make_instructor_headers,
    make_learner_headers,
    make_admin_headers,
    make_anonymous_headers,
)


# ─── Tier 0: Clock + base accounts ─────────────────────────────────
def set_clock(to_iso8601: str):
    """Set the logical clock to a fixed UTC instant (PRD §2.8)."""
    return get_success_data(
        api_client.set_clock(clock_payload(to_iso8601), make_admin_headers())
    )


def create_instructor(revenue_share_pct=0.50, **overrides):
    """Create one Instructor (PRD §3.1). Returns the Instructor dict."""
    payload = create_instructor_payload(revenue_share_pct=revenue_share_pct, **overrides)
    return get_success_data(
        api_client.create_instructor(payload, make_anonymous_headers())
    )


def create_learner(**overrides):
    """Create one Learner (PRD §3.1). Returns the Learner dict."""
    return get_success_data(
        api_client.create_learner(create_learner_payload(**overrides),
                                  make_anonymous_headers())
    )


# ─── Tier 1: Course / lesson authoring + publishing ────────────────
def create_draft_course(instructor_id, **overrides):
    """Create a DRAFT course owned by instructor_id (PRD §3.2)."""
    headers = make_instructor_headers(instructor_id)
    return get_success_data(
        api_client.create_course(create_course_payload(instructor_id, **overrides), headers)
    )


def add_lesson(instructor_id, course_id, order_index=1, **overrides):
    """Add a lesson to a DRAFT/UNPUBLISHED course (PRD §3.2)."""
    headers = make_instructor_headers(instructor_id)
    return get_success_data(
        api_client.create_lesson(
            create_lesson_payload(course_id, order_index=order_index, **overrides), headers
        )
    )


def publish_course(instructor_id, course_id):
    """Publish (or re-publish) a course (PRD §3.3)."""
    headers = make_instructor_headers(instructor_id)
    return get_success_data(api_client.publish_course(course_id, headers))


def create_published_course(instructor_id, lesson_overrides=None, **course_overrides):
    """Create + publish a single-lesson (non-graded by default) course.

    Returns (course_after_publish, lesson). The instructor must already exist.
    """
    course = create_draft_course(instructor_id, **course_overrides)
    lesson = add_lesson(instructor_id, course["id"], order_index=1,
                        **(lesson_overrides or {}))
    published = publish_course(instructor_id, course["id"])
    return published, lesson


def create_published_graded_course(instructor_id, graded_lessons, **course_overrides):
    """Create + publish a course whose lessons are described by graded_lessons.

    graded_lessons: list of dicts with keys like is_graded, quiz_weight,
    question_count (each becomes a lesson at order_index 1..N).
    Returns (course_after_publish, [lesson, ...]).
    """
    course = create_draft_course(instructor_id, **course_overrides)
    lessons = []
    for idx, spec in enumerate(graded_lessons, start=1):
        lessons.append(add_lesson(instructor_id, course["id"], order_index=idx, **spec))
    published = publish_course(instructor_id, course["id"])
    return published, lessons


# ─── Tier 2: Coupon / bundle authoring ─────────────────────────────
def create_coupon(instructor_id, course_id, code="SAVE", **overrides):
    """Create an ACTIVE coupon on a course owned by instructor_id (PRD §3.5)."""
    headers = make_instructor_headers(instructor_id)
    return get_success_data(
        api_client.create_coupon(
            create_coupon_payload(instructor_id, course_id, code=code, **overrides), headers
        )
    )


def create_bundle(instructor_id, course_ids, bundle_price_cents, **overrides):
    """Create an ACTIVE bundle over course_ids (PRD §3.6).

    Returns the Bundle dict (carries version for the OCC enroll path)."""
    headers = make_instructor_headers(instructor_id)
    return get_success_data(
        api_client.create_bundle(
            create_bundle_payload(instructor_id, course_ids, bundle_price_cents, **overrides),
            headers,
        )
    )


def create_bundle_of_published_courses(instructor_id, list_prices, bundle_price_cents,
                                       **bundle_overrides):
    """Create N published single-lesson courses with the given list prices, then a
    bundle over them at bundle_price_cents (PRD §3.2, §3.3, §3.6).

    Returns (bundle, [course, ...]). The instructor must already exist.
    """
    courses = []
    for i, price in enumerate(list_prices, start=1):
        course, _ = create_published_course(
            instructor_id, title=f"BundleCourse{i}", list_price_cents=price
        )
        courses.append(course)
    bundle = create_bundle(
        instructor_id, [c["id"] for c in courses], bundle_price_cents, **bundle_overrides
    )
    return bundle, courses


# ─── Tier 3: Enrollment lifecycle ──────────────────────────────────
def enroll_in_course(learner_id, course_id, **overrides):
    """Enroll a learner in a single course (PRD §3.4). Returns the Enrollment dict."""
    headers = make_learner_headers(learner_id)
    return get_success_data(
        api_client.enroll_course(course_id, enroll_course_payload(learner_id, **overrides),
                                 headers)
    )


def enroll_in_bundle(learner_id, bundle_id, expected_bundle_version):
    """Enroll a learner in all member courses of a bundle (PRD §3.6).

    Returns the Enrollment[] array."""
    headers = make_learner_headers(learner_id)
    return get_success_data(
        api_client.enroll_bundle(
            bundle_id, enroll_bundle_payload(learner_id, expected_bundle_version), headers
        )
    )


def complete_lesson(learner_id, enrollment_id, lesson_id, **overrides):
    """Record a lesson completion (PRD §3.7). Returns the LessonCompletion dict."""
    headers = make_learner_headers(learner_id)
    return get_success_data(
        api_client.create_lesson_completion(
            create_lesson_completion_payload(enrollment_id, lesson_id, **overrides), headers
        )
    )


def setup_active_single_course_enrollment(list_price_cents=1000, refund_window_days=30,
                                          revenue_share_pct=0.50, clock="2026-06-01T00:00:00Z",
                                          **course_overrides):
    """Full chain to ONE ACTIVE single-course enrollment (PRD §3.1–§3.4).

    Sets the clock, creates instructor + learner, a published single-lesson course, and
    enrolls the learner. Returns dict with instructor, learner, course, lesson, enrollment.
    """
    if clock is not None:
        set_clock(clock)
    instructor = create_instructor(revenue_share_pct=revenue_share_pct)
    learner = create_learner()
    course, lesson = create_published_course(
        instructor["id"], list_price_cents=list_price_cents,
        refund_window_days=refund_window_days, **course_overrides
    )
    enrollment = enroll_in_course(learner["id"], course["id"])
    return {
        "instructor": instructor,
        "learner": learner,
        "course": course,
        "lesson": lesson,
        "enrollment": enrollment,
    }


def setup_refunded_enrollment(list_price_cents=4000, refund_window_days=30,
                              revenue_share_pct=0.50, clock="2026-06-01T00:00:00Z"):
    """ACTIVE single-course enrollment then self-refunded within the window (PRD §3.9).

    Returns dict with instructor, learner, course, enrollment (the refunded one)."""
    ctx = setup_active_single_course_enrollment(
        list_price_cents=list_price_cents, refund_window_days=refund_window_days,
        revenue_share_pct=revenue_share_pct, clock=clock,
    )
    headers = make_learner_headers(ctx["learner"]["id"])
    refunded = get_success_data(
        api_client.refund_enrollment(ctx["enrollment"]["id"], headers)
    )
    ctx["enrollment"] = refunded
    return ctx


def setup_completed_enrollment(ceu_credits=0.0, clock="2026-06-01T00:00:00Z",
                               **course_overrides):
    """ACTIVE enrollment in a single-lesson non-graded course, then COMPLETED by
    finishing the one lesson (PRD §3.7, §3.8). completion_threshold defaults to 1.00.

    Returns dict with instructor, learner, course, lesson, enrollment (COMPLETED)."""
    course_overrides.setdefault("completion_threshold_pct", 1.00)
    course_overrides.setdefault("list_price_cents", 0)
    if clock is not None:
        set_clock(clock)
    instructor = create_instructor()
    learner = create_learner()
    course, lesson = create_published_course(
        instructor["id"], ceu_credits=ceu_credits, **course_overrides
    )
    enrollment = enroll_in_course(learner["id"], course["id"])
    complete_lesson(learner["id"], enrollment["id"], lesson["id"])
    refreshed = get_success_data(
        api_client.get_enrollment(enrollment["id"], make_learner_headers(learner["id"]))
    )
    return {
        "instructor": instructor,
        "learner": learner,
        "course": course,
        "lesson": lesson,
        "enrollment": refreshed,
    }


def setup_expired_enrollment(list_price_cents=4000, refund_window_days=5,
                             enrolled_clock="2026-06-01T00:00:00Z",
                             expired_clock="2026-06-10T00:00:00Z", revenue_share_pct=0.50):
    """ACTIVE enrollment whose refund window has passed and is lazily EXPIRED via a read
    (PRD §3.9). The SALE ledger entry flips PENDING->AVAILABLE.

    Returns dict with instructor, learner, course, enrollment (EXPIRED after the read)."""
    ctx = setup_active_single_course_enrollment(
        list_price_cents=list_price_cents, refund_window_days=refund_window_days,
        revenue_share_pct=revenue_share_pct, clock=enrolled_clock,
    )
    set_clock(expired_clock)
    expired = get_success_data(
        api_client.get_enrollment(ctx["enrollment"]["id"],
                                  make_learner_headers(ctx["learner"]["id"]))
    )
    ctx["enrollment"] = expired
    return ctx


# ─── Tier 4: Payout lifecycle ──────────────────────────────────────
def request_payout(instructor_id, requested_amount_cents):
    """Request a payout (PRD §3.11). Returns the Payout dict."""
    headers = make_instructor_headers(instructor_id)
    return get_success_data(
        api_client.create_payout(
            create_payout_payload(instructor_id, requested_amount_cents), headers
        )
    )


def setup_instructor_with_available_balance(list_price_cents=4000, refund_window_days=5,
                                            revenue_share_pct=0.50,
                                            enrolled_clock="2026-06-01T00:00:00Z",
                                            expired_clock="2026-06-10T00:00:00Z"):
    """Instructor whose single sale has expired its refund window, moving the share into
    payout_balance_cents (PRD §3.9, §2.7).

    Returns dict with instructor, learner, course, enrollment (EXPIRED). Read the
    instructor afterwards to observe payout_balance_cents == instructor_share.
    """
    return setup_expired_enrollment(
        list_price_cents=list_price_cents, refund_window_days=refund_window_days,
        revenue_share_pct=revenue_share_pct, enrolled_clock=enrolled_clock,
        expired_clock=expired_clock,
    )


def get_instructor(instructor_id):
    """Read an instructor (recomputes balances) (PRD §3.1)."""
    return get_success_data(
        api_client.get_instructor(instructor_id, make_instructor_headers(instructor_id))
    )


# ─── Tier 5: Review lifecycle ──────────────────────────────────────
def create_published_review(learner_id, enrollment_id, stars=5, body="Great"):
    """Post a PUBLISHED review for an eligible enrollment (PRD §3.10)."""
    headers = make_learner_headers(learner_id)
    return get_success_data(
        api_client.create_review(
            create_review_payload(enrollment_id, stars=stars, body=body), headers
        )
    )


def setup_completed_enrollment_with_review(stars=5, clock="2026-06-01T00:00:00Z"):
    """A COMPLETED single-lesson enrollment carrying one PUBLISHED review (PRD §3.8, §3.10).

    Returns dict with instructor, learner, course, enrollment, review.
    """
    ctx = setup_completed_enrollment(clock=clock)
    review = create_published_review(ctx["learner"]["id"], ctx["enrollment"]["id"], stars=stars)
    ctx["review"] = review
    return ctx
