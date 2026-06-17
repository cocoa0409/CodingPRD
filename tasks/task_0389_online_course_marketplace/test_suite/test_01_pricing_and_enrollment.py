"""Enrollment pricing: single-course coupon discounting and bundle largest-remainder
allocation, plus enrollment creation defaults and system fields (PRD §3.4, §3.6).

Queue A: dual_variant_calc (single vs bundle divergence), combinatorial_formula
(coupon branch min/max round; bundle floor-then-distribute). Queue B: course defaults,
instructor revenue-share default, enrollment system-field generation.
"""
import pytest

from test_helpers import (
    validate_success,
    assert_course,
    assert_enrollment,
    set_clock,
    create_instructor,
    create_learner,
    create_published_course,
    create_coupon,
    create_bundle_of_published_courses,
    enroll_in_course,
    enroll_in_bundle,
    make_instructor_headers,
    make_learner_headers,
    make_anonymous_headers,
    create_instructor_payload,
    create_course_payload,
    enroll_course_payload,
)


# ===========================================================================
# Queue A — dual_variant_calc / pricing_single_vs_bundle_allocation_diverge
# ===========================================================================
def test_bundle_allocation_splits_flat_price_by_list_weight(api):
    """PRD §3.6: "The flat `bundle_price_cents` is split across the member courses by
    list-price weight using the largest-remainder method, so that the per-course gross
    prices sum to exactly the bundle price with no cent lost or invented."

    Bundle 7333c over list prices 5000/3000/2000 allocates to gross 3666/2200/1467,
    summing to exactly 7333.

    Design: Difficulty/dual_variant_calc/pricing_single_vs_bundle_allocation_diverge
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    bundle, courses = create_bundle_of_published_courses(
        instructor["id"], list_prices=[5000, 3000, 2000], bundle_price_cents=7333
    )
    enrollments = enroll_in_bundle(learner["id"], bundle["id"], bundle["version"])
    assert len(enrollments) == 3, f"expected 3 member enrollments, got {len(enrollments)}"
    by_course = {e["course_id"]: e for e in enrollments}
    assert by_course[courses[0]["id"]]["gross_price_cents"] == 3666
    assert by_course[courses[1]["id"]]["gross_price_cents"] == 2200
    assert by_course[courses[2]["id"]]["gross_price_cents"] == 1467
    total = sum(e["gross_price_cents"] for e in enrollments)
    assert total == 7333, f"member gross must sum to bundle_price_cents 7333, got {total}"


def test_bundle_gross_diverges_from_single_course_list_price(api):
    """PRD §3.6: "For each member course, a raw share is the bundle price multiplied by
    that course's `list_price_cents` divided by `sum_list_price_cents`; each course's
    provisional share is the floor of its raw share."

    The C1 member gross under the bundle is 3666, NOT its 5000 single-course list price;
    its instructor_share is round_half_up(3666 * 0.50) = 1833.

    Design: Difficulty/dual_variant_calc/pricing_single_vs_bundle_allocation_diverge
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    bundle, courses = create_bundle_of_published_courses(
        instructor["id"], list_prices=[5000, 3000, 2000], bundle_price_cents=7333
    )
    enrollments = enroll_in_bundle(learner["id"], bundle["id"], bundle["version"])
    c1 = next(e for e in enrollments if e["course_id"] == courses[0]["id"])
    assert c1["gross_price_cents"] == 3666, (
        f"bundle gross 3666 must differ from single-course list 5000, got {c1['gross_price_cents']}"
    )
    assert c1["gross_price_cents"] != 5000
    assert c1["instructor_share_cents"] == 1833, (
        f"round_half_up(3666*0.50)==1833, got {c1['instructor_share_cents']}"
    )


# ===========================================================================
# Queue A — combinatorial_formula / single_course_coupon_branch_minmax_round_mode_a
# ===========================================================================
def test_percent_coupon_discount_rounds_half_up(api):
    """PRD §3.4: "a `PERCENT` coupon discounts the base list price by its `discount_value`
    percent, with the discount amount computed as the list price multiplied by the
    discount value divided by 100 and rounded half-up to the nearest cent; ... The gross
    price is then the list price minus the discount, but never below zero."

    list 10000, PERCENT 25 -> discount round_half_up(10000*25/100)=2500 -> gross 7500.

    Design: Difficulty/combinatorial_formula/single_course_coupon_branch_minmax_round_mode_a
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, _ = create_published_course(instructor["id"], list_price_cents=10000)
    create_coupon(instructor["id"], course["id"], code="SAVE25",
                  discount_type="PERCENT", discount_value=25, max_redemptions=100,
                  valid_from="2026-01-01T00:00:00Z", valid_until="2027-01-01T00:00:00Z")
    enrollment = enroll_in_course(learner["id"], course["id"], coupon_code="SAVE25")
    assert enrollment["gross_price_cents"] == 7500, (
        f"10000 - 2500 == 7500, got {enrollment['gross_price_cents']}"
    )


def test_percent_coupon_derives_instructor_share_and_platform_fee(api):
    """PRD §3.4: "`instructor_share_cents` is the gross price multiplied by the owning
    instructor's `revenue_share_pct`, rounded half-up to the nearest cent, and
    `platform_fee_cents` is the gross price minus the instructor share."

    gross 7500, share 0.50 -> instructor_share round_half_up(7500*0.50)=3750,
    platform_fee 7500-3750=3750.

    Design: Difficulty/combinatorial_formula/single_course_coupon_branch_minmax_round_mode_a
    """
    set_clock("2026-06-01T00:00:00Z")
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, _ = create_published_course(instructor["id"], list_price_cents=10000)
    create_coupon(instructor["id"], course["id"], code="SAVE25",
                  discount_type="PERCENT", discount_value=25, max_redemptions=100,
                  valid_from="2026-01-01T00:00:00Z", valid_until="2027-01-01T00:00:00Z")
    enrollment = enroll_in_course(learner["id"], course["id"], coupon_code="SAVE25")
    assert enrollment["instructor_share_cents"] == 3750, (
        f"round_half_up(7500*0.50)==3750, got {enrollment['instructor_share_cents']}"
    )
    assert enrollment["platform_fee_cents"] == 3750, (
        f"7500-3750==3750, got {enrollment['platform_fee_cents']}"
    )


# ===========================================================================
# Queue A — combinatorial_formula / bundle_largest_remainder_round_then_distribute_mode_b
# ===========================================================================
def test_bundle_remainder_cents_go_to_largest_fractional_parts(api):
    """PRD §3.6: "The leftover — the bundle price minus the sum of all the floored
    shares, always a non-negative whole number of cents — is then distributed one cent
    at a time to the courses with the largest fractional parts of their raw shares, with
    ties broken by the member course's `created_at` ascending."

    raw shares 3666.5/2199.9/1466.6: C1 floor 3666 (no cent), C2 floor 2199 + 1 (frac .9),
    C3 floor 1466 + 1 (frac .6) -> 3666/2200/1467.

    Design: Difficulty/combinatorial_formula/bundle_largest_remainder_round_then_distribute_mode_b
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    bundle, courses = create_bundle_of_published_courses(
        instructor["id"], list_prices=[5000, 3000, 2000], bundle_price_cents=7333
    )
    enrollments = enroll_in_bundle(learner["id"], bundle["id"], bundle["version"])
    by_course = {e["course_id"]: e for e in enrollments}
    assert by_course[courses[0]["id"]]["gross_price_cents"] == 3666, "C1 floor 3666, no remainder"
    assert by_course[courses[1]["id"]]["gross_price_cents"] == 2200, "C2 floor 2199 + 1 (frac .9)"
    assert by_course[courses[2]["id"]]["gross_price_cents"] == 1467, "C3 floor 1466 + 1 (frac .6)"


def test_bundle_allocation_conserves_total_no_cent_invented(api):
    """PRD §3.6: "so that the per-course gross prices sum to exactly the bundle price
    with no cent lost or invented."

    Floor-then-distribute yields {3666,2200,1467} summing to exactly 7333; a naive
    per-share round-half-up would give {3667,2200,1467} summing to 7334.

    Design: Difficulty/combinatorial_formula/bundle_largest_remainder_round_then_distribute_mode_b
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    bundle, courses = create_bundle_of_published_courses(
        instructor["id"], list_prices=[5000, 3000, 2000], bundle_price_cents=7333
    )
    enrollments = enroll_in_bundle(learner["id"], bundle["id"], bundle["version"])
    total = sum(e["gross_price_cents"] for e in enrollments)
    assert total == 7333, f"allocation must sum to exactly 7333, got {total}"
    c1 = next(e for e in enrollments if e["course_id"] == courses[0]["id"])
    assert c1["gross_price_cents"] == 3666, (
        f"floor-then-distribute pins C1 at 3666 (not naive 3667), got {c1['gross_price_cents']}"
    )


# ===========================================================================
# Queue B — entities / enrollment_system_fields_generated_input_ignored
# ===========================================================================
def test_enrollment_computes_gross_server_side_and_is_active(api):
    """PRD §3.4: "With no coupon, the gross price (`gross_price_cents`) equals the
    snapshot list price." and "A successful single-course enrollment is born `ACTIVE`
    at `version` 1".

    Enrolling in a list-2000 course with no coupon yields server-computed
    gross_price_cents 2000, status ACTIVE, version 1.

    Design: Corner/entities/enrollment_system_fields_generated_input_ignored
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    learner = create_learner()
    course, _ = create_published_course(instructor["id"], list_price_cents=2000)
    res = api.enroll_course(course["id"], enroll_course_payload(learner["id"]),
                            make_learner_headers(learner["id"]))
    enrollment = validate_success(res, 201)
    assert_enrollment(enrollment)
    assert enrollment["gross_price_cents"] == 2000, (
        f"server-computed gross == list 2000, got {enrollment['gross_price_cents']}"
    )
    assert enrollment["status"] == "ACTIVE"
    assert enrollment["version"] == 1


# ===========================================================================
# Queue B — entities / create_course_returns_201_with_defaults_applied
# ===========================================================================
def test_create_course_applies_defaults(api):
    """PRD §3.2: "Several pedagogical and commercial parameters are optional at creation
    and fall back to defaults: `passing_score_pct` (... default 0.70); `refund_window_days`
    (... default 30); `drip_enabled` (... default false); `ceu_credits` (... default 0.0);
    and `completion_threshold_pct` (... default 1.00). A course is born in `DRAFT` status."

    Creating a course with only required fields returns 201 with those defaults.

    Design: Corner/entities/create_course_returns_201_with_defaults_applied
    """
    instructor = create_instructor(revenue_share_pct=0.50)
    res = api.create_course(
        create_course_payload(instructor["id"], title="Defaults", list_price_cents=1000),
        make_instructor_headers(instructor["id"]),
    )
    course = validate_success(res, 201)
    assert_course(course)
    assert course["status"] == "DRAFT"
    assert course["passing_score_pct"] == 0.70
    assert course["refund_window_days"] == 30
    assert course["drip_enabled"] is False
    assert course["completion_threshold_pct"] == 1.00


# ===========================================================================
# Queue B — entities / instructor_revenue_share_default_applied
# ===========================================================================
def test_instructor_revenue_share_defaults_to_half(api):
    """PRD §3.1: "an optional `revenue_share_pct`; when the share is omitted it defaults
    to 0.50".

    Creating an instructor without revenue_share_pct applies 0.50.

    Design: Corner/entities/instructor_revenue_share_default_applied
    """
    payload = create_instructor_payload()
    payload.pop("revenue_share_pct", None)
    res = api.create_instructor(payload, make_anonymous_headers())
    instructor = validate_success(res, 201)
    assert instructor["revenue_share_pct"] == 0.50, (
        f"omitted revenue_share_pct defaults to 0.50, got {instructor['revenue_share_pct']}"
    )
