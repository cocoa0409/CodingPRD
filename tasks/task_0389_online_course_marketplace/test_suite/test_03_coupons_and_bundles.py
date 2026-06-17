"""Coupon lifecycle and redemption constraints, bundle creation rules, and drip gating
(PRD §3.5, §3.6, §3.7).

Queue A: non_linear_state_machine (coupon ACTIVE->EXHAUSTED->ACTIVE cycle),
boundary_precision_check (coupon valid_until exclusive), resource_temporal_overlap
(coupon half-open overlap; bundle promo buffer). Queue B: coupon course mismatch,
invalid bundle price, disabled-coupon redemption, drip lock, coupon disable terminality.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    set_clock,
    create_instructor,
    create_learner,
    create_published_course,
    create_coupon,
    enroll_in_course,
    make_instructor_headers,
    make_learner_headers,
    create_coupon_payload,
    create_bundle_payload,
    enroll_course_payload,
    create_lesson_completion_payload,
)


# ===========================================================================
# Queue A — non_linear_state_machine / coupon_cycle_active_exhausted_active
# ===========================================================================
def test_coupon_exhausts_when_last_redemption_consumed(api):
    """PRD §3.4: "should that increment bring `redeemed_count` up to `max_redemptions`,
    the coupon transitions `ACTIVE → EXHAUSTED` so that no further redemption is allowed."

    A max_redemptions=1 coupon redeemed once goes EXHAUSTED with redeemed_count 1.

    Design: Difficulty/non_linear_state_machine/coupon_cycle_active_exhausted_active
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, _ = create_published_course(instructor["id"], list_price_cents=5000,
                                        refund_window_days=30)
    coupon = create_coupon(instructor["id"], course["id"], code="ONE",
                           discount_type="FLAT", discount_value=1000, max_redemptions=1,
                           valid_from="2026-01-01T00:00:00Z", valid_until="2027-01-01T00:00:00Z")
    enroll_in_course(learner["id"], course["id"], coupon_code="ONE")
    after = validate_success(
        api.get_coupon(coupon["id"], make_instructor_headers(instructor["id"])), 200
    )
    assert after["status"] == "EXHAUSTED", "reaching max_redemptions exhausts the coupon"
    assert after["redeemed_count"] == 1


def test_coupon_returns_to_active_when_redemption_freed_by_refund(api):
    """PRD §3.9: "if the coupon had been `EXHAUSTED` it transitions back from `EXHAUSTED`
    to `ACTIVE` now that a redemption has been freed (the `EXHAUSTED → ACTIVE`
    transition, recomputing the coupon's `status` and `version`)."

    Refunding the only enrollment that exhausted a max_redemptions=1 coupon returns it to
    ACTIVE with redeemed_count back to 0.

    Design: Difficulty/non_linear_state_machine/coupon_cycle_active_exhausted_active
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, _ = create_published_course(instructor["id"], list_price_cents=5000,
                                        refund_window_days=30)
    coupon = create_coupon(instructor["id"], course["id"], code="ONE",
                           discount_type="FLAT", discount_value=1000, max_redemptions=1,
                           valid_from="2026-01-01T00:00:00Z", valid_until="2027-01-01T00:00:00Z")
    enrollment = enroll_in_course(learner["id"], course["id"], coupon_code="ONE")
    validate_success(
        api.refund_enrollment(enrollment["id"], make_learner_headers(learner["id"])), 200
    )
    after = validate_success(
        api.get_coupon(coupon["id"], make_instructor_headers(instructor["id"])), 200
    )
    assert after["status"] == "ACTIVE", "refund frees a redemption, EXHAUSTED->ACTIVE"
    assert after["redeemed_count"] == 0


# ===========================================================================
# Queue A — boundary_precision_check / coupon_valid_until_exclusive_boundary_on_enroll
# ===========================================================================
def test_coupon_at_exact_valid_until_is_not_redeemable(api):
    """PRD §3.5: "a coupon is usable only when it is currently `ACTIVE` and the clock sits
    within its window, meaning the current instant is at or after `valid_from` and
    strictly before `valid_until`; a coupon outside its window or not `ACTIVE` is rejected
    with `ERR_COUPON_NOT_REDEEMABLE` (HTTP 422)."

    With the clock set exactly to valid_until, now == valid_until is out of the half-open
    window, so redemption is rejected.

    Design: Difficulty/boundary_precision_check/coupon_valid_until_exclusive_boundary_on_enroll
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, _ = create_published_course(instructor["id"], list_price_cents=5000)
    create_coupon(instructor["id"], course["id"], code="EDGE",
                  discount_type="PERCENT", discount_value=10, max_redemptions=5,
                  valid_from="2026-01-01T00:00:00Z", valid_until="2026-07-01T00:00:00Z")
    set_clock("2026-07-01T00:00:00Z")
    res = api.enroll_course(course["id"], enroll_course_payload(learner["id"], coupon_code="EDGE"),
                            make_learner_headers(learner["id"]))
    validate_error(res, ApiErrorId.ERR_COUPON_NOT_REDEEMABLE.value)


def test_coupon_strictly_before_valid_until_is_redeemable(api):
    """PRD §3.5: "the current instant is at or after `valid_from` and strictly before
    `valid_until`".

    With the clock just before valid_until, redemption succeeds (the inclusive lower /
    exclusive upper boundary admits now < valid_until).

    Design: Difficulty/boundary_precision_check/coupon_valid_until_exclusive_boundary_on_enroll
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, _ = create_published_course(instructor["id"], list_price_cents=5000)
    create_coupon(instructor["id"], course["id"], code="EDGE",
                  discount_type="PERCENT", discount_value=10, max_redemptions=5,
                  valid_from="2026-01-01T00:00:00Z", valid_until="2026-07-01T00:00:00Z")
    set_clock("2026-06-30T23:59:59Z")
    res = api.enroll_course(course["id"], enroll_course_payload(learner["id"], coupon_code="EDGE"),
                            make_learner_headers(learner["id"]))
    enrollment = validate_success(res, 201)
    # list 5000, PERCENT 10 -> discount round_half_up(5000*10/100)=500 -> gross 4500
    assert enrollment["gross_price_cents"] == 4500, (
        f"redemption strictly before valid_until applies the 10% discount, got "
        f"{enrollment['gross_price_cents']}"
    )


# ===========================================================================
# Queue A — resource_temporal_overlap / coupon_window_halfopen_overlap_rejected
# ===========================================================================
def test_overlapping_coupon_window_for_same_course_rejected(api):
    """PRD §3.5: "Two windows overlap, and the create is rejected with
    `ERR_COUPON_WINDOW_OVERLAP` (HTTP 409), exactly when the new window's `valid_from` is
    strictly before the existing window's `valid_until` and the existing window's
    `valid_from` is strictly before the new window's `valid_until`."

    Existing [2026-01-01, 2026-06-01); new [2026-03-01, 2026-09-01) overlaps and is rejected.

    Design: Difficulty/resource_temporal_overlap/coupon_window_halfopen_overlap_rejected
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    course, _ = create_published_course(instructor["id"], list_price_cents=5000)
    create_coupon(instructor["id"], course["id"], code="WIN1",
                  discount_type="PERCENT", discount_value=10, max_redemptions=5,
                  valid_from="2026-01-01T00:00:00Z", valid_until="2026-06-01T00:00:00Z")
    res = api.create_coupon(
        create_coupon_payload(instructor["id"], course["id"], code="WIN2",
                              discount_type="PERCENT", discount_value=20, max_redemptions=5,
                              valid_from="2026-03-01T00:00:00Z", valid_until="2026-09-01T00:00:00Z"),
        make_instructor_headers(instructor["id"]),
    )
    validate_error(res, ApiErrorId.ERR_COUPON_WINDOW_OVERLAP.value)


def test_touching_coupon_window_for_same_course_allowed(api):
    """PRD §3.5: "The windows are half-open: two coupons whose windows merely touch at an
    endpoint — where one's `valid_until` equals the other's `valid_from` — do not overlap
    and are permitted."

    Existing [2026-01-01, 2026-06-01); new [2026-06-01, 2026-09-01) touches at the
    endpoint and is allowed.

    Design: Difficulty/resource_temporal_overlap/coupon_window_halfopen_overlap_rejected
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    course, _ = create_published_course(instructor["id"], list_price_cents=5000)
    create_coupon(instructor["id"], course["id"], code="WIN1",
                  discount_type="PERCENT", discount_value=10, max_redemptions=5,
                  valid_from="2026-01-01T00:00:00Z", valid_until="2026-06-01T00:00:00Z")
    res = api.create_coupon(
        create_coupon_payload(instructor["id"], course["id"], code="WIN2",
                              discount_type="PERCENT", discount_value=20, max_redemptions=5,
                              valid_from="2026-06-01T00:00:00Z", valid_until="2026-09-01T00:00:00Z"),
        make_instructor_headers(instructor["id"]),
    )
    coupon = validate_success(res, 201)
    assert coupon["status"] == "ACTIVE", "touching windows are permitted (half-open)"


# ===========================================================================
# Queue A — resource_temporal_overlap / bundle_promo_buffer_gap_rejected
# ===========================================================================
def _two_published_courses(instructor_id, prices=(3000, 2000)):
    courses = []
    for i, price in enumerate(prices, start=1):
        c, _ = create_published_course(instructor_id, title=f"PC{i}", list_price_cents=price)
        courses.append(c)
    return courses


def test_bundle_promo_within_one_day_buffer_rejected(api):
    """PRD §3.6: "Two such bundles collide — and the create is rejected with
    `ERR_BUNDLE_PROMO_OVERLAP` (HTTP 409) — when the new window's `promo_starts_at` is
    before the existing window's `promo_ends_at` extended forward by one day, and at the
    same time the existing window's `promo_starts_at` is before the new window's
    `promo_ends_at` extended forward by one day."

    Existing promo ends 2026-02-01; new starts 2026-02-01T12:00 (only 12h later) on a
    shared member course -> rejected (gap < 1 day).

    Design: Difficulty/resource_temporal_overlap/bundle_promo_buffer_gap_rejected
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    courses = _two_published_courses(instructor["id"])
    cids = [c["id"] for c in courses]
    validate_success(
        api.create_bundle(
            create_bundle_payload(instructor["id"], cids, bundle_price_cents=4000,
                                  promo_starts_at="2026-01-01T00:00:00Z",
                                  promo_ends_at="2026-02-01T00:00:00Z"),
            make_instructor_headers(instructor["id"]),
        ), 201,
    )
    res = api.create_bundle(
        create_bundle_payload(instructor["id"], cids, bundle_price_cents=4000,
                              promo_starts_at="2026-02-01T12:00:00Z",
                              promo_ends_at="2026-03-01T00:00:00Z"),
        make_instructor_headers(instructor["id"]),
    )
    validate_error(res, ApiErrorId.ERR_BUNDLE_PROMO_OVERLAP.value)


def test_bundle_promo_with_full_day_gap_allowed(api):
    """PRD §3.6: "Under these closed-with-buffer semantics, windows that merely touch, or
    that leave any gap shorter than one full day, are rejected; only a gap of at least one
    day between sharing bundles is allowed."

    Existing promo ends 2026-02-01; new starts 2026-02-02 (a full day later) -> allowed.

    Design: Difficulty/resource_temporal_overlap/bundle_promo_buffer_gap_rejected
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    courses = _two_published_courses(instructor["id"])
    cids = [c["id"] for c in courses]
    validate_success(
        api.create_bundle(
            create_bundle_payload(instructor["id"], cids, bundle_price_cents=4000,
                                  promo_starts_at="2026-01-01T00:00:00Z",
                                  promo_ends_at="2026-02-01T00:00:00Z"),
            make_instructor_headers(instructor["id"]),
        ), 201,
    )
    res = api.create_bundle(
        create_bundle_payload(instructor["id"], cids, bundle_price_cents=4000,
                              promo_starts_at="2026-02-02T00:00:00Z",
                              promo_ends_at="2026-03-01T00:00:00Z"),
        make_instructor_headers(instructor["id"]),
    )
    bundle = validate_success(res, 201)
    assert bundle["status"] == "ACTIVE", "a full-day gap clears the buffer"


# ===========================================================================
# Queue B — validations / coupon_course_mismatch_rejected
# ===========================================================================
def test_coupon_for_other_course_rejected_on_enroll(api):
    """PRD §3.5: "The resolved coupon must also belong to the course being enrolled: its
    `course_id` must equal the enrolled course and its issuing instructor must own that
    course, or the enrollment is rejected with `ERR_COUPON_COURSE_MISMATCH` (HTTP 422)."

    A coupon scoped to course A used while enrolling in course B is rejected.

    Design: Corner/validations/coupon_course_mismatch_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course_a, _ = create_published_course(instructor["id"], title="A", list_price_cents=5000)
    course_b, _ = create_published_course(instructor["id"], title="B", list_price_cents=5000)
    create_coupon(instructor["id"], course_a["id"], code="ONLYA",
                  discount_type="PERCENT", discount_value=10, max_redemptions=5,
                  valid_from="2026-01-01T00:00:00Z", valid_until="2027-01-01T00:00:00Z")
    res = api.enroll_course(
        course_b["id"], enroll_course_payload(learner["id"], coupon_code="ONLYA"),
        make_learner_headers(learner["id"]),
    )
    validate_error(res, ApiErrorId.ERR_COUPON_COURSE_MISMATCH.value)


# ===========================================================================
# Queue B — validations / invalid_bundle_price_not_below_sum_rejected
# ===========================================================================
def test_bundle_price_not_below_member_sum_rejected(api):
    """PRD §3.6: "the `bundle_price_cents` must be strictly less than the sum of the
    member courses' list prices; a bundle that violates either rule is rejected with
    `ERR_INVALID_BUNDLE` (HTTP 422)."

    Two courses summing to 5000 with a bundle priced at 5000 (not strictly less) is rejected.

    Design: Corner/validations/invalid_bundle_price_not_below_sum_rejected
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    courses = _two_published_courses(instructor["id"], prices=(3000, 2000))
    res = api.create_bundle(
        create_bundle_payload(instructor["id"], [c["id"] for c in courses],
                              bundle_price_cents=5000,
                              promo_starts_at="2026-01-01T00:00:00Z",
                              promo_ends_at="2026-12-31T00:00:00Z"),
        make_instructor_headers(instructor["id"]),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_BUNDLE.value)


# ===========================================================================
# Queue B — errors / coupon_disabled_not_redeemable_rejected
# ===========================================================================
def test_disabled_coupon_not_redeemable(api):
    """PRD §3.5: "a coupon is usable only when it is currently `ACTIVE` and the clock sits
    within its window ... a coupon outside its window or not `ACTIVE` is rejected with
    `ERR_COUPON_NOT_REDEEMABLE` (HTTP 422)."

    A DISABLED coupon (not ACTIVE) is rejected at redemption.

    Design: Corner/errors/coupon_disabled_not_redeemable_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, _ = create_published_course(instructor["id"], list_price_cents=5000)
    coupon = create_coupon(instructor["id"], course["id"], code="OFF",
                           discount_type="PERCENT", discount_value=10, max_redemptions=5,
                           valid_from="2026-01-01T00:00:00Z", valid_until="2027-01-01T00:00:00Z")
    validate_success(
        api.disable_coupon(coupon["id"], make_instructor_headers(instructor["id"])), 200
    )
    res = api.enroll_course(course["id"], enroll_course_payload(learner["id"], coupon_code="OFF"),
                            make_learner_headers(learner["id"]))
    validate_error(res, ApiErrorId.ERR_COUPON_NOT_REDEEMABLE.value)


# ===========================================================================
# Queue B — state_machines / coupon_republish_cycle_after_disable_returns_invalid_state
# ===========================================================================
def test_disable_already_disabled_coupon_invalid_state(api):
    """PRD §3.5: "disabling a coupon takes it from `ACTIVE` to `DISABLED`, after which it
    can never be redeemed; `DISABLED` is terminal."

    A second disable on an already-DISABLED coupon is rejected with ERR_INVALID_STATE
    (the transition requires status ACTIVE).

    Design: Corner/state_machines/coupon_republish_cycle_after_disable_returns_invalid_state
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    course, _ = create_published_course(instructor["id"], list_price_cents=1000)
    coupon = create_coupon(instructor["id"], course["id"], code="DIS",
                           discount_type="PERCENT", discount_value=10, max_redemptions=5,
                           valid_from="2026-01-01T00:00:00Z", valid_until="2027-01-01T00:00:00Z")
    validate_success(
        api.disable_coupon(coupon["id"], make_instructor_headers(instructor["id"])), 200
    )
    res = api.disable_coupon(coupon["id"], make_instructor_headers(instructor["id"]))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Queue B — validations / drip_locked_lesson_rejected
# ===========================================================================
def test_drip_locked_lesson_rejected_before_unlock(api):
    """PRD §3.7: "When the course has drip enabled, the lesson is additionally locked
    until the clock reaches `enrolled_at` plus the lesson's `drip_offset_days`; an attempt
    before that instant is rejected with `ERR_LESSON_LOCKED` (HTTP 409)."

    A drip-enabled lesson with drip_offset_days 7, attempted on day 2 after enrollment,
    is rejected.

    Design: Corner/validations/drip_locked_lesson_rejected
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, lesson = create_published_course(
        instructor["id"], list_price_cents=0, drip_enabled=True, completion_threshold_pct=1.00,
        lesson_overrides={"drip_offset_days": 7},
    )
    enrollment = enroll_in_course(learner["id"], course["id"])
    set_clock("2026-06-03T00:00:00Z")
    res = api.create_lesson_completion(
        create_lesson_completion_payload(enrollment["id"], lesson["id"]),
        make_learner_headers(learner["id"]),
    )
    validate_error(res, ApiErrorId.ERR_LESSON_LOCKED.value)
