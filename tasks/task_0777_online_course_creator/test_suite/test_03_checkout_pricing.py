"""Checkout: the charge calculation, coupons, and the cross-entity enroll gates."""
from test_helpers import (
    ApiErrorId, validate_success, validate_error,
    make_creator_headers, make_student_headers,
    fixtures as fx,
)


# --------------------------------------------------------------------------
# Difficulty: combinatorial checkout charge (PERCENT coupon).
# --------------------------------------------------------------------------

def test_percent_coupon_discount_is_floored(api):
    """PRD §3.4: "for a `PERCENT` coupon it is the list price multiplied by the discount
    value divided by 100, rounded down; for a `FIXED` coupon it is the smaller of the
    discount value and the list price (so a discount can never exceed the price)."

    Design: Difficulty/combinatorial_formula/checkout_charge_percent_coupon_mode_a
    """
    ctx = fx.setup_enrollment(
        amount_cents=20000,
        coupon={"code": "P25", "discount_type": "PERCENT", "discount_value": 25,
                "min_purchase_cents": 10000},
        coupon_code="P25",
    )
    enr = ctx["enrollment"]
    assert enr["discount_cents"] == 5000


def test_percent_coupon_list_price_and_initial_charge(api):
    """PRD §3.4: "First the list price, stored as `list_price_cents`, is taken from the
    plan's `amount_cents`: for `ONE_TIME` it is the amount, for `PAYMENT_PLAN` it is the
    amount as the total across all installments, and for `SUBSCRIPTION` it is the amount
    of the first cycle." PRD §3.4: "For `ONE_TIME`, both the initial charge and the
    scheduled total equal the discounted total."

    Design: Difficulty/combinatorial_formula/checkout_charge_percent_coupon_mode_a
    """
    ctx = fx.setup_enrollment(
        amount_cents=20000,
        coupon={"code": "P25", "discount_type": "PERCENT", "discount_value": 25,
                "min_purchase_cents": 10000},
        coupon_code="P25",
    )
    enr = ctx["enrollment"]
    assert enr["list_price_cents"] == 20000
    assert enr["initial_charge_cents"] == 15000


# --------------------------------------------------------------------------
# Difficulty: coupon min_purchase inclusive boundary.
# --------------------------------------------------------------------------

def test_coupon_min_purchase_equal_boundary_applies(api):
    """PRD §3.4: "the list price is at least its `min_purchase_cents`." PRD §3.4: "for a
    `PERCENT` coupon it is the list price multiplied by the discount value divided by 100,
    rounded down"

    Design: Difficulty/boundary_precision_check/coupon_min_purchase_inclusive_boundary
    """
    ctx = fx.setup_enrollment(
        amount_cents=15000,
        coupon={"code": "MIN15K", "discount_type": "PERCENT", "discount_value": 10,
                "min_purchase_cents": 15000},
        coupon_code="MIN15K",
    )
    enr = ctx["enrollment"]
    assert enr["list_price_cents"] == 15000
    assert enr["discount_cents"] == 1500


def test_coupon_min_purchase_just_below_boundary_rejected(api):
    """PRD §3.4: "a list price below the minimum is `ERR_COUPON_MIN_PURCHASE_NOT_MET`"

    Design: Difficulty/boundary_precision_check/coupon_min_purchase_inclusive_boundary
    """
    ctx = fx.setup_published_course(
        amount_cents=14999,
        coupon={"code": "MIN15K", "discount_type": "PERCENT", "discount_value": 10,
                "min_purchase_cents": 15000},
    )
    resp = api.create_enrollment(
        {"student_id": ctx["student"]["id"], "course_id": ctx["course"]["id"],
         "price_plan_id": ctx["plan"]["id"], "coupon_code": "MIN15K"},
        make_student_headers(ctx["student"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_COUPON_MIN_PURCHASE_NOT_MET.value)


# --------------------------------------------------------------------------
# Corner: calculations.
# --------------------------------------------------------------------------

def test_fixed_coupon_discount_applied(api):
    """PRD §3.4: "for a `FIXED` coupon it is the smaller of the discount value and the
    list price (so a discount can never exceed the price)." PRD §3.4: "For `ONE_TIME`,
    both the initial charge and the scheduled total equal the discounted total."

    Design: Corner/calculations/fixed_coupon_discount_applied
    """
    ctx = fx.setup_enrollment(
        amount_cents=20000,
        coupon={"code": "FIX3K", "discount_type": "FIXED", "discount_value": 3000},
        coupon_code="FIX3K",
    )
    enr = ctx["enrollment"]
    assert enr["discount_cents"] == 3000
    assert enr["initial_charge_cents"] == 17000


def test_payment_plan_installments_sum_to_discounted_total(api):
    """PRD §3.4: "For `PAYMENT_PLAN`, the scheduled total equals the discounted total, and
    the initial charge equals the first installment." PRD §3.4: "Each installment except
    the last is the discounted total divided by the installment count, rounded up"

    Design: Corner/calculations/installment_split_sums_to_discounted_total
    """
    ctx = fx.setup_enrollment(plan_type="PAYMENT_PLAN", amount_cents=10000, num_installments=3)
    enr = validate_success(
        api.get_enrollment(ctx["enrollment"]["id"], make_student_headers(ctx["student"]["id"])))
    assert enr["scheduled_total_cents"] == 10000
    assert enr["initial_charge_cents"] == 3334


# --------------------------------------------------------------------------
# Corner: enroll-time validation gates.
# --------------------------------------------------------------------------

def test_coupon_window_expired_rejected(api):
    """PRD §3.4: "a current clock outside the coupon window is `ERR_COUPON_WINDOW_EXPIRED`,
    a list price below the minimum is `ERR_COUPON_MIN_PURCHASE_NOT_MET`, and an
    already-exhausted coupon (redeemed count at or above the maximum) is
    `ERR_COUPON_REDEMPTION_LIMIT`."

    Design: Corner/validations/coupon_window_expired_returns_422
    """
    ctx = fx.setup_published_course(
        coupon={"code": "EXP", "discount_type": "PERCENT", "discount_value": 10,
                "starts_at": "2026-01-01T00:00:00Z", "expires_at": "2026-02-01T00:00:00Z"},
    )
    resp = api.create_enrollment(
        {"student_id": ctx["student"]["id"], "course_id": ctx["course"]["id"],
         "price_plan_id": ctx["plan"]["id"], "coupon_code": "EXP"},
        make_student_headers(ctx["student"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_COUPON_WINDOW_EXPIRED.value)


def test_coupon_min_purchase_below_boundary_rejected(api):
    """PRD §3.4: "a list price below the minimum is `ERR_COUPON_MIN_PURCHASE_NOT_MET`"

    Design: Corner/validations/coupon_min_purchase_below_boundary_returns_422
    """
    ctx = fx.setup_published_course(
        amount_cents=14999,
        coupon={"code": "MIN15K", "discount_type": "PERCENT", "discount_value": 10,
                "min_purchase_cents": 15000},
    )
    resp = api.create_enrollment(
        {"student_id": ctx["student"]["id"], "course_id": ctx["course"]["id"],
         "price_plan_id": ctx["plan"]["id"], "coupon_code": "MIN15K"},
        make_student_headers(ctx["student"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_COUPON_MIN_PURCHASE_NOT_MET.value)


def test_affiliate_creator_mismatch_rejected(api):
    """PRD §3.4: "any affiliate must belong to the course's creator, comparing the
    affiliate's `creator_id` to the course's `creator_id` (`ERR_AFFILIATE_CREATOR_MISMATCH`)."

    Design: Corner/validations/affiliate_creator_mismatch_returns_422
    """
    creator1 = fx.create_creator(email="c1@x.com")
    creator2 = fx.create_creator(email="c2@x.com")
    student = fx.create_student()
    course = fx.create_course(creator1["id"], title="A")
    fx.create_lesson(course["id"], creator1["id"], title="L1", position=1)
    plan = fx.create_price_plan(course["id"], creator1["id"],
                                plan_type="ONE_TIME", amount_cents=20000)
    fx.create_affiliate(creator2["id"], code="FOR2", commission_pct=10)
    fx.publish_course(course["id"], creator1["id"])
    resp = api.create_enrollment(
        {"student_id": student["id"], "course_id": course["id"],
         "price_plan_id": plan["id"], "affiliate_code": "FOR2"},
        make_student_headers(student["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_AFFILIATE_CREATOR_MISMATCH.value)


def test_duplicate_enrollment_rejected(api):
    """PRD §3.4: "A student may hold only one non-terminal enrollment per course — if the
    student already has an enrollment in this course whose billing is not `CANCELLED` or
    `REFUNDED`, checkout is rejected with `ERR_DUPLICATE_ENROLLMENT`."

    Design: Corner/validations/duplicate_enrollment_returns_409
    """
    ctx = fx.setup_enrollment()
    resp = api.create_enrollment(
        {"student_id": ctx["student"]["id"], "course_id": ctx["course"]["id"],
         "price_plan_id": ctx["plan"]["id"]},
        make_student_headers(ctx["student"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENROLLMENT.value)


def test_enroll_for_another_student_rejected_as_not_owner(api):
    """PRD §2.1: "When an authenticated user acts on a resource they do not own — a creator
    manipulating another creator's course, or a student progressing another student's
    enrollment — the request is rejected with `ERR_NOT_OWNER`."

    Design: Corner/validations/enroll_wrong_student_owner_returns_403
    """
    creator = fx.create_creator()
    student_a = fx.create_student(email="s1@x.com")
    student_b = fx.create_student(email="s2@x.com")
    course = fx.create_course(creator["id"], title="A")
    fx.create_lesson(course["id"], creator["id"], title="L1", position=1)
    plan = fx.create_price_plan(course["id"], creator["id"],
                                plan_type="ONE_TIME", amount_cents=20000)
    fx.publish_course(course["id"], creator["id"])
    # Header identifies student_a, but the body enrolls student_b.
    resp = api.create_enrollment(
        {"student_id": student_b["id"], "course_id": course["id"], "price_plan_id": plan["id"]},
        make_student_headers(student_a["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_OWNER.value)


def test_enroll_with_archived_plan_rejected(api):
    """PRD §3.4: "the price plan must be `ACTIVE`, else `ERR_PRICE_PLAN_INACTIVE`"

    Design: Corner/errors/enroll_with_archived_plan_returns_409
    """
    creator = fx.create_creator()
    student = fx.create_student()
    course = fx.create_course(creator["id"], title="A")
    fx.create_lesson(course["id"], creator["id"], title="L1", position=1)
    plan1 = fx.create_price_plan(course["id"], creator["id"],
                                 plan_type="ONE_TIME", amount_cents=20000)
    fx.create_price_plan(course["id"], creator["id"],
                         plan_type="ONE_TIME", amount_cents=30000)
    fx.publish_course(course["id"], creator["id"])
    fx.archive_price_plan(plan1["id"], creator["id"])
    resp = api.create_enrollment(
        {"student_id": student["id"], "course_id": course["id"], "price_plan_id": plan1["id"]},
        make_student_headers(student["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PRICE_PLAN_INACTIVE.value)
