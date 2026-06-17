"""Catalog CRUD edge cases, listing / reverse-reach reads, review eligibility and
moderation, duplicate guards, field validation, and RBAC (PRD §2.1, §2.3, §2.5, §3.2,
§3.4, §3.7, §3.10).

All Queue B: entities (404 / required-field / type-range), endpoints (paginated list /
reverse-reach), errors (order-index collision / correct-answers over count), validations
(duplicate enrollment / duplicate completion / review-not-eligible), state_machines
(review hide recompute), rbac (role and ownership denials, unauthenticated).
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    MISSING_UUID,
    set_clock,
    create_instructor,
    create_learner,
    create_draft_course,
    create_published_course,
    create_published_graded_course,
    add_lesson,
    enroll_in_course,
    complete_lesson,
    request_payout,
    create_published_review,
    make_instructor_headers,
    make_learner_headers,
    make_admin_headers,
    make_headers,
    create_course_payload,
    create_lesson_payload,
    create_review_payload,
    enroll_course_payload,
    create_lesson_completion_payload,
    approve_payout_payload,
)


# ===========================================================================
# Queue B — entities / get_course_not_found_returns_404
# ===========================================================================
def test_get_missing_course_returns_not_found(api):
    """PRD §2.5: "the system validates those identifiers left to right and rejects the
    request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve
    to an existing resource".

    GET /courses/{id} for a well-formed but non-existent id returns ERR_NOT_FOUND.

    Design: Corner/entities/get_course_not_found_returns_404
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    res = api.get_course(MISSING_UUID, make_instructor_headers(instructor["id"]))
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Queue B — entities / create_course_missing_required_field_returns_invalid_request
# ===========================================================================
def test_create_course_without_list_price_invalid_request(api):
    """PRD §2.11: "Generic field-level input validation — required fields present, enum
    values legal, numbers within their permitted ranges — carries `ERR_INVALID_REQUEST`
    (HTTP 400)".

    POST /courses without the required list_price_cents (no default) returns
    ERR_INVALID_REQUEST.

    Design: Corner/entities/create_course_missing_required_field_returns_invalid_request
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    payload = create_course_payload(instructor["id"], title="NoPrice")
    payload.pop("list_price_cents", None)
    res = api.create_course(payload, make_instructor_headers(instructor["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Queue B — entities / review_stars_out_of_range_returns_invalid_request
# ===========================================================================
def test_review_stars_above_five_invalid_request(api):
    """PRD §3.10: "supplies a `stars` rating from 1 to 5 inclusive".

    Posting a review with stars=6 on an eligible (COMPLETED) enrollment is rejected with
    ERR_INVALID_REQUEST.

    Design: Corner/entities/review_stars_out_of_range_returns_invalid_request
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, lesson = create_published_course(
        instructor["id"], list_price_cents=0, completion_threshold_pct=1.00
    )
    enrollment = enroll_in_course(learner["id"], course["id"])
    complete_lesson(learner["id"], enrollment["id"], lesson["id"])
    res = api.create_review(
        create_review_payload(enrollment["id"], stars=6, body="too high"),
        make_learner_headers(learner["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Queue B — endpoints / list_courses_filtered_by_instructor_paginated
# ===========================================================================
def test_list_courses_by_instructor_paginated(api):
    """PRD §2.3: "Every list response carries the pagination bookkeeping inside the `meta`
    object: `limit`, `offset`, `total_count`, and `has_more`."

    GET /courses?instructor_id=X returns the instructor's two courses with total_count 2
    and has_more false.

    Design: Corner/endpoints/list_courses_filtered_by_instructor_paginated
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    headers = make_instructor_headers(instructor["id"])
    validate_success(
        api.create_course(create_course_payload(instructor["id"], title="One", list_price_cents=100),
                          headers), 201,
    )
    validate_success(
        api.create_course(create_course_payload(instructor["id"], title="Two", list_price_cents=200),
                          headers), 201,
    )
    res = api.list_courses(headers, params={"instructor_id": instructor["id"], "limit": 10, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is False
    assert all(c["instructor_id"] == instructor["id"] for c in data)


# ===========================================================================
# Queue B — endpoints / reverse_reach_lessons_by_course
# ===========================================================================
def test_list_lessons_by_course_reverse_reach(api):
    """PRD §2.5: "A handful of read endpoints reach back along a foreign key — listing a
    course's lessons ... — by accepting the parent identifier as a filter or a leading
    path segment."

    GET /lessons?course_id=X returns the two Lesson children of that course.

    Design: Corner/endpoints/reverse_reach_lessons_by_course
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    course = create_draft_course(instructor["id"], list_price_cents=100)
    add_lesson(instructor["id"], course["id"], order_index=1)
    add_lesson(instructor["id"], course["id"], order_index=2)
    res = api.list_lessons(make_instructor_headers(instructor["id"]),
                           params={"course_id": course["id"]})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 2, f"expected 2 lessons, got {meta['total_count']}"
    assert all(lesson["course_id"] == course["id"] for lesson in data)


# ===========================================================================
# Queue B — errors / lesson_order_index_collision_rejected
# ===========================================================================
def test_duplicate_lesson_order_index_rejected(api):
    """PRD §3.2: "an `order_index`, a 1-based position within the course that must be
    unique among that course's lessons — a colliding `order_index` on creation is rejected
    with `ERR_DUPLICATE_LESSON_COMPLETION` (HTTP 409)."

    Adding a second lesson at an already-used order_index is rejected.

    Design: Corner/errors/lesson_order_index_collision_rejected
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    course = create_draft_course(instructor["id"], list_price_cents=100)
    add_lesson(instructor["id"], course["id"], order_index=1)
    res = api.create_lesson(
        create_lesson_payload(course["id"], order_index=1, title="dup"),
        make_instructor_headers(instructor["id"]),
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_LESSON_COMPLETION.value)


# ===========================================================================
# Queue B — errors / correct_answers_exceed_question_count_rejected
# ===========================================================================
def test_correct_answers_over_question_count_invalid_request(api):
    """PRD §3.7: "For graded lessons, `correct_answers` must not exceed the lesson's
    `question_count`."

    A completion with correct_answers 8 against a question_count-5 graded lesson is
    rejected with ERR_INVALID_REQUEST.

    Design: Corner/errors/correct_answers_exceed_question_count_rejected
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, lessons = create_published_graded_course(
        instructor["id"],
        graded_lessons=[{"is_graded": True, "quiz_weight": 1, "question_count": 5}],
        list_price_cents=0, passing_score_pct=0.70, completion_threshold_pct=1.00,
    )
    enrollment = enroll_in_course(learner["id"], course["id"])
    res = api.create_lesson_completion(
        create_lesson_completion_payload(enrollment["id"], lessons[0]["id"], correct_answers=8),
        make_learner_headers(learner["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


# ===========================================================================
# Queue B — validations / duplicate_enrollment_rejected
# ===========================================================================
def test_duplicate_enrollment_rejected(api):
    """PRD §3.4: "if an enrollment in `ACTIVE`, `COMPLETED`, or `EXPIRED` status already
    exists for this learner-and-course pair, a new enrollment attempt is rejected with
    `ERR_ALREADY_ENROLLED` (HTTP 409)."

    A second enrollment in the same course while an ACTIVE one exists is rejected.

    Design: Corner/validations/duplicate_enrollment_rejected
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, _ = create_published_course(instructor["id"], list_price_cents=1000)
    enroll_in_course(learner["id"], course["id"])
    res = api.enroll_course(course["id"], enroll_course_payload(learner["id"]),
                            make_learner_headers(learner["id"]))
    validate_error(res, ApiErrorId.ERR_ALREADY_ENROLLED.value)


# ===========================================================================
# Queue B — validations / duplicate_lesson_completion_rejected
# ===========================================================================
def test_duplicate_lesson_completion_rejected(api):
    """PRD §3.7: "no completion already exists for this enrollment-and-lesson pair; a
    duplicate pair is rejected with `ERR_DUPLICATE_LESSON_COMPLETION` (HTTP 409)."

    A second completion for the same (enrollment, lesson) pair is rejected.

    Design: Corner/validations/duplicate_lesson_completion_rejected
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, lessons = create_published_graded_course(
        instructor["id"],
        graded_lessons=[{"is_graded": False}, {"is_graded": False}],
        list_price_cents=0, completion_threshold_pct=1.00,
    )
    enrollment = enroll_in_course(learner["id"], course["id"])
    complete_lesson(learner["id"], enrollment["id"], lessons[0]["id"])
    res = api.create_lesson_completion(
        create_lesson_completion_payload(enrollment["id"], lessons[0]["id"]),
        make_learner_headers(learner["id"]),
    )
    validate_error(res, ApiErrorId.ERR_DUPLICATE_LESSON_COMPLETION.value)


# ===========================================================================
# Queue B — validations / review_not_eligible_active_enrollment_rejected
# ===========================================================================
def test_review_on_active_enrollment_not_eligible(api):
    """PRD §3.10: "A review is eligible only when the referenced enrollment is owned by
    the acting learner and is in `COMPLETED` or `EXPIRED` status ... a request failing
    either condition is rejected with `ERR_REVIEW_NOT_ELIGIBLE` (HTTP 422)."

    Reviewing a still-ACTIVE enrollment is rejected.

    Design: Corner/validations/review_not_eligible_active_enrollment_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, _ = create_published_course(
        instructor["id"], list_price_cents=1000, refund_window_days=30,
        completion_threshold_pct=1.00,
    )
    enrollment = enroll_in_course(learner["id"], course["id"])
    res = api.create_review(
        create_review_payload(enrollment["id"], stars=4, body="too early"),
        make_learner_headers(learner["id"]),
    )
    validate_error(res, ApiErrorId.ERR_REVIEW_NOT_ELIGIBLE.value)


# ===========================================================================
# Queue B — state_machines / review_hide_then_unhide_recomputes_rating
# ===========================================================================
def test_hiding_only_review_drops_rating_to_null(api):
    """PRD §3.10: "Each of these three transitions cascades to the course's rating: hiding
    and retracting recompute `average_rating` and `rating_count` with the affected review
    excluded".

    Hiding the only PUBLISHED review drops the course's rating_count to 0 and
    average_rating to null.

    Design: Corner/state_machines/review_hide_then_unhide_recomputes_rating
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, lesson = create_published_course(
        instructor["id"], list_price_cents=0, completion_threshold_pct=1.00
    )
    enrollment = enroll_in_course(learner["id"], course["id"])
    complete_lesson(learner["id"], enrollment["id"], lesson["id"])
    review = create_published_review(learner["id"], enrollment["id"], stars=5)
    validate_success(api.hide_review(review["id"], make_admin_headers()), 200)
    refreshed = validate_success(
        api.get_course(course["id"], make_instructor_headers(instructor["id"])), 200
    )
    assert refreshed["rating_count"] == 0, "hiding the only review drops rating_count to 0"
    assert refreshed["average_rating"] is None, "no published reviews -> average_rating null"


# ===========================================================================
# Queue B — rbac / learner_cannot_publish_course_forbidden
# ===========================================================================
def test_learner_cannot_publish_course(api):
    """PRD §2.1: "Once a caller is authenticated, the system additionally checks that the
    declared role is permitted to perform the requested operation ... a failure of either
    check is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    A Learner calling the Instructor-only publish endpoint is denied with ERR_FORBIDDEN.

    Design: Corner/rbac/learner_cannot_publish_course_forbidden
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course = create_draft_course(instructor["id"], list_price_cents=100)
    add_lesson(instructor["id"], course["id"], order_index=1)
    res = api.publish_course(course["id"], make_learner_headers(learner["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Queue B — rbac / instructor_cannot_approve_payout_forbidden
# ===========================================================================
def test_instructor_cannot_approve_payout(api):
    """PRD §2.1: "the system additionally checks that the declared role is permitted to
    perform the requested operation ... a failure of either check is rejected with
    `ERR_FORBIDDEN` (HTTP 403)."

    An Instructor calling the PlatformAdmin-only payout approve endpoint is denied. The
    instructor is first funded by a window-expiry flip so the REQUESTED payout can be
    created (a payout requires payout_balance_cents >= 1 per PRD §3.11).

    Design: Corner/rbac/instructor_cannot_approve_payout_forbidden
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, _ = create_published_course(instructor["id"], list_price_cents=4000,
                                        refund_window_days=5)
    enrollment = enroll_in_course(learner["id"], course["id"])
    set_clock("2026-06-10T00:00:00Z")
    validate_success(
        api.get_enrollment(enrollment["id"], make_learner_headers(learner["id"])), 200
    )  # 2000c becomes payable
    payout = request_payout(instructor["id"], 100)
    res = api.approve_payout(
        payout["id"], approve_payout_payload(1),
        make_instructor_headers(instructor["id"]),
    )
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Queue B — rbac / learner_cannot_refund_other_learners_enrollment_forbidden
# ===========================================================================
def test_learner_cannot_refund_other_learners_enrollment(api):
    """PRD §2.1: "ownership checks on any resource that references a learner (an
    enrollment's `learner_id`, and by extension the enrollment behind a lesson-completion,
    a refund, or a review) compare that foreign key to `X-User-ID`."

    Learner B refunding Learner A's enrollment is denied with ERR_FORBIDDEN.

    Design: Corner/rbac/learner_cannot_refund_other_learners_enrollment_forbidden
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner_a = create_learner()
    learner_b = create_learner()
    course, _ = create_published_course(instructor["id"], list_price_cents=1000,
                                        refund_window_days=30)
    enrollment = enroll_in_course(learner_a["id"], course["id"])
    res = api.refund_enrollment(enrollment["id"], make_learner_headers(learner_b["id"]))
    validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Queue B — rbac / missing_auth_headers_returns_unauthenticated
# ===========================================================================
def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "When either header is missing, or `X-User-Role` is not one of the
    recognized role names, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Calling the protected POST /courses with an X-User-Role that is not one of the
    recognized role names is rejected with ERR_UNAUTHENTICATED.

    Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    res = api.create_course(
        create_course_payload(instructor["id"], title="NoAuth", list_price_cents=100),
        make_headers("someone", "NotARole"),
    )
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)
