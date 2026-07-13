"""Coupon window overlap, validation precedence, and redemption-count conservation."""
from test_helpers import (
    ApiErrorId, validate_success, validate_error,
    make_creator_headers, make_student_headers,
    fixtures as fx,
)


def _course_with_active_coupon(code, starts_at, expires_at):
    creator = fx.create_creator()
    course = fx.create_course(creator["id"], title="A")
    fx.create_coupon(course["id"], creator["id"], code=code, discount_type="PERCENT",
                     discount_value=10, max_redemptions=5,
                     starts_at=starts_at, expires_at=expires_at)
    return creator, course


# --------------------------------------------------------------------------
# Difficulty: coupon-window overlap uses CLOSED intervals.
# --------------------------------------------------------------------------

def test_coupon_windows_touching_endpoint_overlap_rejected(api):
    """PRD §3.3: "Two active coupons that share the same `code` on the same course may not
    have overlapping validity windows — the windows are treated as closed intervals, and a
    create whose window overlaps an existing active same-code coupon is rejected with
    `ERR_COUPON_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/coupon_code_window_overlap_closed_intervals
    """
    creator, course = _course_with_active_coupon(
        "SAVE", "2026-03-01T00:00:00Z", "2026-03-31T00:00:00Z")
    resp = api.create_coupon(
        {"course_id": course["id"], "code": "SAVE", "discount_type": "PERCENT",
         "discount_value": 10, "max_redemptions": 5,
         "starts_at": "2026-03-31T00:00:00Z", "expires_at": "2026-04-30T00:00:00Z"},
        make_creator_headers(creator["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_COUPON_WINDOW_OVERLAP.value)


def test_coupon_windows_interior_overlap_rejected(api):
    """PRD §3.3: "Two active coupons that share the same `code` on the same course may not
    have overlapping validity windows — the windows are treated as closed intervals, and a
    create whose window overlaps an existing active same-code coupon is rejected with
    `ERR_COUPON_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/coupon_code_window_overlap_closed_intervals
    """
    creator, course = _course_with_active_coupon(
        "SAVE", "2026-03-01T00:00:00Z", "2026-03-31T00:00:00Z")
    resp = api.create_coupon(
        {"course_id": course["id"], "code": "SAVE", "discount_type": "PERCENT",
         "discount_value": 10, "max_redemptions": 5,
         "starts_at": "2026-03-15T00:00:00Z", "expires_at": "2026-04-15T00:00:00Z"},
        make_creator_headers(creator["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_COUPON_WINDOW_OVERLAP.value)


# --------------------------------------------------------------------------
# Difficulty: referential mismatch (priority 7) masks the fiscal limit (priority 11).
# --------------------------------------------------------------------------

def test_coupon_course_mismatch_masks_redemption_limit(api):
    """PRD §2.1: "(7) cross-referenced resources belong together; (8) cross-entity status
    gates hold; (9) time-window gates hold; (10) interval-overlap and uniqueness gates hold;
    (11) quota and fiscal gates hold; and finally (12) the optimistic-concurrency check for
    payout creation. Earlier checks always mask later ones." PRD §3.4: "any coupon must
    belong to the course (`ERR_COUPON_COURSE_MISMATCH`)"

    Design: Difficulty/priority_pair_validation_conflict/coupon_referential_beats_fiscal
    """
    creator = fx.create_creator()
    student = fx.create_student()
    # Course A (target of the mismatching coupon).
    course_a = fx.create_course(creator["id"], title="A")
    fx.create_lesson(course_a["id"], creator["id"], title="LA", position=1)
    plan_a = fx.create_price_plan(course_a["id"], creator["id"],
                                  plan_type="ONE_TIME", amount_cents=20000)
    fx.publish_course(course_a["id"], creator["id"])
    # Course B owns coupon LIMIT1 (max 1), redeemed once => at its fiscal limit.
    course_b = fx.create_course(creator["id"], title="B")
    fx.create_lesson(course_b["id"], creator["id"], title="LB", position=1)
    plan_b = fx.create_price_plan(course_b["id"], creator["id"],
                                  plan_type="ONE_TIME", amount_cents=20000)
    fx.create_coupon(course_b["id"], creator["id"], code="LIMIT1", discount_type="PERCENT",
                     discount_value=10, max_redemptions=1)
    fx.publish_course(course_b["id"], creator["id"])
    fx.create_enrollment(student["id"], course_b["id"], plan_b["id"], coupon_code="LIMIT1")
    # Apply the at-limit, course-B coupon to course A: referential mismatch wins.
    resp = api.create_enrollment(
        {"student_id": student["id"], "course_id": course_a["id"],
         "price_plan_id": plan_a["id"], "coupon_code": "LIMIT1"},
        make_student_headers(student["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_COUPON_COURSE_MISMATCH.value)


def test_coupon_course_mismatch_fires_without_fiscal_conflict(api):
    """PRD §3.4: "any coupon must belong to the course (`ERR_COUPON_COURSE_MISMATCH`)"

    Design: Difficulty/priority_pair_validation_conflict/coupon_referential_beats_fiscal
    """
    creator = fx.create_creator()
    student = fx.create_student()
    course_a = fx.create_course(creator["id"], title="A")
    fx.create_lesson(course_a["id"], creator["id"], title="LA", position=1)
    plan_a = fx.create_price_plan(course_a["id"], creator["id"],
                                  plan_type="ONE_TIME", amount_cents=20000)
    fx.publish_course(course_a["id"], creator["id"])
    # A fresh, un-redeemed coupon on a different course B (no fiscal issue).
    course_b = fx.create_course(creator["id"], title="B")
    fx.create_coupon(course_b["id"], creator["id"], code="OTHER", discount_type="PERCENT",
                     discount_value=10, max_redemptions=5)
    resp = api.create_enrollment(
        {"student_id": student["id"], "course_id": course_a["id"],
         "price_plan_id": plan_a["id"], "coupon_code": "OTHER"},
        make_student_headers(student["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_COUPON_COURSE_MISMATCH.value)


# --------------------------------------------------------------------------
# Difficulty: coupon redeemed_count conserved across enroll(+1) then cancel(-1).
# --------------------------------------------------------------------------

def _read_coupon(api, coupon_id, creator_id):
    return validate_success(api.get_coupon(coupon_id, make_creator_headers(creator_id)))


def test_coupon_redeemed_count_returns_to_zero_after_cancel(api):
    """PRD §3.3: "The coupon reports a conserved `redeemed_count`: the number of
    enrollments that used it whose `billing_status` is neither `CANCELLED` nor `REFUNDED`."
    PRD §3.4: "If a coupon was applied, the coupon's `redeemed_count` immediately counts
    this enrollment."

    Design: Difficulty/compensating_invariant/coupon_redemption_count_conservation_on_cancel
    """
    ctx = fx.setup_enrollment(
        coupon={"code": "C10", "discount_type": "PERCENT", "discount_value": 10,
                "min_purchase_cents": 0},
        coupon_code="C10",
    )
    coupon_id = ctx["coupon"]["id"]
    creator_id = ctx["creator"]["id"]
    assert _read_coupon(api, coupon_id, creator_id)["redeemed_count"] == 1
    fx.get_success_data(api.cancel_enrollment(
        ctx["enrollment"]["id"], {}, make_student_headers(ctx["student"]["id"])))
    assert _read_coupon(api, coupon_id, creator_id)["redeemed_count"] == 0


def test_cancel_drops_enrollment_out_of_coupon_and_terminalizes(api):
    """PRD §3.7: "Cancelling drives `billing_status` from `PENDING` or `CURRENT` to
    `CANCELLED`, drives `access_status` to `REVOKED`, voids every `PENDING` invoice on the
    enrollment to `VOID`, and — because the enrollment is now terminal — removes it from
    any coupon's `redeemed_count` as a compensating decrement."

    Design: Difficulty/compensating_invariant/coupon_redemption_count_conservation_on_cancel
    """
    ctx = fx.setup_enrollment(
        coupon={"code": "C10", "discount_type": "PERCENT", "discount_value": 10,
                "min_purchase_cents": 0},
        coupon_code="C10",
    )
    cancelled = fx.get_success_data(api.cancel_enrollment(
        ctx["enrollment"]["id"], {}, make_student_headers(ctx["student"]["id"])))
    assert cancelled["billing_status"] == "CANCELLED"
    assert cancelled["access_status"] == "REVOKED"
    assert _read_coupon(api, ctx["coupon"]["id"], ctx["creator"]["id"])["redeemed_count"] == 0
