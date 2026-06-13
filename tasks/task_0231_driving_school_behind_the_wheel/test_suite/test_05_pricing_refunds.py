"""Discount stacking, dual-variant refunds, per-line payout rounding, and the
money-conservation invariant.

Difficulty queue A: rules `dual_variant_calc`, `combinatorial_formula`,
`compensating_invariant` (money).
"""
from test_helpers import (
    validate_success, validate_paginated,
    TEST_USERS,
    set_clock, create_student, create_package, create_active_enrollment,
    create_instructor, create_vehicle, create_granted_consent,
    schedule_and_complete, schedule_lesson, complete_lesson_at,
    assert_money_conserved,
)

ADMIN = TEST_USERS["admin_headers"]


# Both-tracks refundable package: price 90000, fee 5000, road 6, bundle 5000.
def _refund_pkg(**ov):
    base = dict(price_cents=90000, enrollment_fee_cents=5000,
                included_classroom_hours=30, included_online_hours=8,
                included_road_hours=6, bundle_discount_cents=5000)
    base.update(ov)
    return create_package(**base)


def _build_enrollment_with_2_road_completed(clock_start="2026-06-01T00:00:00.000Z",
                                            activated_at_clock="2026-06-01T00:00:00.000Z"):
    """Adult ACTIVE enrollment (final 85000), 2 COMPLETED road hours. Returns
    (student, enrollment, package, instructor, vehicle). Leaves clock at the
    completion instant (2026-06-02T16:00)."""
    set_clock(activated_at_clock)
    pkg = _refund_pkg()
    inst = create_instructor(certified_road=True, hourly_rate_cents=5000)
    veh = create_vehicle(dual_control=True)
    stu = create_student(date_of_birth="1990-05-01")
    enr = create_active_enrollment(stu["id"], pkg["id"])
    assert enr["final_price_cents"] == 85000
    from test_helpers import api_client
    validate_success(api_client.record_permit(stu["id"], {"permit_number": "P-100"}, ADMIN))
    schedule_and_complete(
        stu["id"], enr["id"], "ROAD",
        "2026-06-02T14:00:00.000Z", "2026-06-02T16:00:00.000Z",
        inst["id"], "2026-06-02T16:00:00.000Z", vehicle_id=veh["id"],
    )
    return stu, enr, pkg, inst, veh


# ===========================================================================
# dual_variant_calc / refund_pro_rata_vs_schedule_tier_diverge
# ===========================================================================
def test_refund_pro_rata_amount_on_two_of_six_road_hours(api):
    """PRD §3.5: "the consumed hours are the student's `completed_road_hours` of
    road instruction under this enrollment, the remaining hours are the
    package's `included_road_hours` minus those consumed (clamped to zero if
    that would go negative), and the refund is the refundable base multiplied by
    the ratio of remaining hours to the package's `included_road_hours`, rounded
    to a whole cent half up."
    PRD §3.5: "the refundable base is the enrollment's `final_price_cents` minus
    the package's `enrollment_fee_cents`, since the enrollment fee is never
    returned."

    Design: Difficulty/dual_variant_calc/refund_pro_rata_vs_schedule_tier_diverge
    """
    stu, enr, _pkg, _inst, _veh = _build_enrollment_with_2_road_completed()
    set_clock("2026-06-11T00:00:00.000Z")  # 10 days elapsed (irrelevant to PRO_RATA)
    refunded = validate_success(
        api.refund_enrollment(enr["id"],
                              {"refund_method": "PRO_RATA",
                               "refund_destination": "WALLET"}, ADMIN)
    )
    assert refunded["refunded_cents"] == 53333
    assert refunded["refund_method"] == "PRO_RATA"


def test_refund_schedule_tier_diverges_from_pro_rata_same_inputs(api):
    """PRD §3.5: "Under `SCHEDULE_TIER`, the refund is tiered on calendar time
    since activation and ignores hours consumed: take the whole number of
    elapsed days, computed by flooring the gap between the current clock and the
    enrollment's `activated_at` to whole days; if that is at most 3 days the
    refund percentage is one hundred percent, otherwise if at most 14 days it is
    seventy-five percent ... the refund is the refundable base multiplied by
    that percentage, rounded to a whole cent half up."

    Design: Difficulty/dual_variant_calc/refund_pro_rata_vs_schedule_tier_diverge
    """
    stu, enr, _pkg, _inst, _veh = _build_enrollment_with_2_road_completed()
    set_clock("2026-06-11T00:00:00.000Z")  # 10 days since 2026-06-01 activation -> 75%
    refunded = validate_success(
        api.refund_enrollment(enr["id"],
                              {"refund_method": "SCHEDULE_TIER",
                               "refund_destination": "WALLET"}, ADMIN)
    )
    # refundable base 80000 * 0.75 == 60000, != the 53333 PRO_RATA figure.
    assert refunded["refunded_cents"] == 60000
    assert refunded["refunded_cents"] != 53333
    assert refunded["refund_method"] == "SCHEDULE_TIER"


# ===========================================================================
# dual_variant_calc / instructor_payout_per_line_vs_sum_then_round
# ===========================================================================
def _build_three_payout_lessons(rate=3333, clock="2026-07-01T00:00:00.000Z",
                               road_hours=10):
    """Three COMPLETED road lessons of 1.5h, 2.0h, 0.75h for one instructor.
    Returns (instructor, [l1, l2, l3]). Months chosen so the period sums all
    three."""
    set_clock(clock)
    pkg = create_package(price_cents=60000, enrollment_fee_cents=0,
                         included_classroom_hours=0, included_online_hours=0,
                         included_road_hours=road_hours, bundle_discount_cents=0)
    inst = create_instructor(certified_road=True, hourly_rate_cents=rate)
    veh = create_vehicle(dual_control=True)
    stu = create_student(date_of_birth="1985-01-01")
    enr = create_active_enrollment(stu["id"], pkg["id"])
    from test_helpers import api_client
    validate_success(api_client.record_permit(stu["id"], {"permit_number": "P-PAY"}, ADMIN))
    # day offsets keyed off the clock's month via explicit ISO strings supplied by caller
    return inst, veh, stu, enr


def test_instructor_payout_per_line_rounding_sums_to_14166(api):
    """PRD §3.10: "The total is built by the round-per-line-then-sum rule: for
    every `COMPLETED` lesson whose timing falls in the period, take that
    lesson's already-rounded `instructor_payout_cents` and add them up — the
    system does not multiply the rate by total hours and round once at the end."

    Design: Difficulty/dual_variant_calc/instructor_payout_per_line_vs_sum_then_round
    """
    inst, veh, stu, enr = _build_three_payout_lessons(clock="2026-07-01T00:00:00.000Z")
    schedule_and_complete(stu["id"], enr["id"], "ROAD",
                         "2026-07-02T09:00:00.000Z", "2026-07-02T10:30:00.000Z",
                         inst["id"], "2026-07-02T10:30:00.000Z", vehicle_id=veh["id"])
    schedule_and_complete(stu["id"], enr["id"], "ROAD",
                         "2026-07-03T09:00:00.000Z", "2026-07-03T11:00:00.000Z",
                         inst["id"], "2026-07-03T11:00:00.000Z", vehicle_id=veh["id"])
    schedule_and_complete(stu["id"], enr["id"], "ROAD",
                         "2026-07-04T09:00:00.000Z", "2026-07-04T09:45:00.000Z",
                         inst["id"], "2026-07-04T09:45:00.000Z", vehicle_id=veh["id"])
    summary = validate_success(
        api.get_payout_summary(inst["id"], ADMIN,
                              params={"period_start": "2026-07-01T00:00:00.000Z",
                                      "period_end": "2026-07-31T00:00:00.000Z"})
    )
    # 5000 + 6666 + 2500 == 14166 (per-line), NOT round(3333*4.25) == 14165.
    assert summary["period_total_cents"] == 14166
    assert summary["period_total_cents"] != 14165


def test_instructor_per_lesson_payout_rounded_individually(api):
    """PRD §3.7: "The instructor's pay for a single completed lesson is the
    instructor's `hourly_rate_cents` multiplied by the lesson's
    `duration_hours`, rounded to a whole cent half up; this per-lesson figure is
    stored on the lesson as `instructor_payout_cents`."

    Design: Difficulty/dual_variant_calc/instructor_payout_per_line_vs_sum_then_round
    """
    inst, veh, stu, enr = _build_three_payout_lessons(clock="2026-07-01T00:00:00.000Z")
    l1 = schedule_lesson(stu["id"], enr["id"], "ROAD",
                        "2026-07-02T09:00:00.000Z", "2026-07-02T10:30:00.000Z",
                        instructor_id=inst["id"], vehicle_id=veh["id"])
    l1 = complete_lesson_at(l1["id"], inst["id"], "2026-07-02T10:30:00.000Z")
    # 3333 * 1.5 == 4999.5 -> round half up -> 5000
    assert l1["instructor_payout_cents"] == 5000


# ===========================================================================
# combinatorial_formula / enrollment_price_three_stacked_discounts_mode_a
# ===========================================================================
def test_enrollment_price_three_stacked_discounts_minor_promo_bundle(api):
    """PRD §3.4: "If the student is a minor, the running subtotal is multiplied
    by one minus the teen discount rate of ten percent ... If the enrollment's
    `promo_code` is the value `FLAT10`, the running subtotal is then multiplied
    by one minus the promo rate of ten percent ... the package's
    `bundle_discount_cents` is subtracted from the running subtotal. ... After
    all three steps, the subtotal is rounded to a whole cent using round half up
    exactly once, and then floored at zero."

    Design: Difficulty/combinatorial_formula/enrollment_price_three_stacked_discounts_mode_a
    """
    set_clock("2026-06-01T00:00:00.000Z")
    pkg = _refund_pkg()
    stu = create_student(full_name="Tina Teen", email="tina@x.com",
                        date_of_birth="2010-03-01")
    create_granted_consent(stu["id"], guardian_name="Gail Guard",
                          guardian_email="gail@x.com")
    enr = create_active_enrollment(stu["id"], pkg["id"], promo_code="FLAT10")
    # 90000 * 0.9 * 0.9 - 5000 == 72900 - 5000 == 67900
    assert enr["final_price_cents"] == 67900
    assert enr["amount_paid_cents"] == 67900
    assert enr["status"] == "ACTIVE"


def test_enrollment_price_minor_is_marked_minor_at_activation(api):
    """PRD §3.4: "Activation then sets `amount_paid_cents` equal to
    `final_price_cents` (the student is recorded as having paid the charged
    amount)."
    PRD §3.2: "the learner is a minor when their age is under 18 at that clock."

    Design: Difficulty/combinatorial_formula/enrollment_price_three_stacked_discounts_mode_a
    """
    set_clock("2026-06-01T00:00:00.000Z")
    pkg = _refund_pkg()
    stu = create_student(full_name="Teri Teen", email="teri@x.com",
                        date_of_birth="2010-03-01")
    fetched = validate_success(api.get_student(stu["id"], ADMIN))
    assert fetched["is_minor"] is True
    create_granted_consent(stu["id"], guardian_email="gail2@x.com")
    enr = create_active_enrollment(stu["id"], pkg["id"], promo_code="FLAT10")
    assert enr["amount_paid_cents"] == enr["final_price_cents"] == 67900


# ===========================================================================
# combinatorial_formula / instructor_payout_rounding_order_mode_b
# ===========================================================================
def test_payout_rounding_order_total_is_14166_not_14165(api):
    """PRD §3.10: "the system does not multiply the rate by total hours and
    round once at the end."
    PRD §3.7: "This per-line rounding matters because the period payout summary,
    described in §3.10, sums these already-rounded per-lesson amounts rather
    than re-deriving from total hours."

    Design: Difficulty/combinatorial_formula/instructor_payout_rounding_order_mode_b
    """
    inst, veh, stu, enr = _build_three_payout_lessons(clock="2026-08-01T00:00:00.000Z")
    schedule_and_complete(stu["id"], enr["id"], "ROAD",
                         "2026-08-02T09:00:00.000Z", "2026-08-02T10:30:00.000Z",
                         inst["id"], "2026-08-02T10:30:00.000Z", vehicle_id=veh["id"])
    schedule_and_complete(stu["id"], enr["id"], "ROAD",
                         "2026-08-03T09:00:00.000Z", "2026-08-03T11:00:00.000Z",
                         inst["id"], "2026-08-03T11:00:00.000Z", vehicle_id=veh["id"])
    schedule_and_complete(stu["id"], enr["id"], "ROAD",
                         "2026-08-04T09:00:00.000Z", "2026-08-04T09:45:00.000Z",
                         inst["id"], "2026-08-04T09:45:00.000Z", vehicle_id=veh["id"])
    summary = validate_success(
        api.get_payout_summary(inst["id"], ADMIN,
                              params={"period_start": "2026-08-01T00:00:00.000Z",
                                      "period_end": "2026-08-31T00:00:00.000Z"})
    )
    assert summary["period_total_cents"] == 14166


def test_payout_rounding_order_per_lesson_values(api):
    """PRD §3.7: "The instructor's pay for a single completed lesson is the
    instructor's `hourly_rate_cents` multiplied by the lesson's
    `duration_hours`, rounded to a whole cent half up; this per-lesson figure is
    stored on the lesson as `instructor_payout_cents`."

    Design: Difficulty/combinatorial_formula/instructor_payout_rounding_order_mode_b
    """
    inst, veh, stu, enr = _build_three_payout_lessons(clock="2026-08-01T00:00:00.000Z")
    l2 = schedule_lesson(stu["id"], enr["id"], "ROAD",
                        "2026-08-03T09:00:00.000Z", "2026-08-03T11:00:00.000Z",
                        instructor_id=inst["id"], vehicle_id=veh["id"])
    l2 = complete_lesson_at(l2["id"], inst["id"], "2026-08-03T11:00:00.000Z")
    l3 = schedule_lesson(stu["id"], enr["id"], "ROAD",
                        "2026-08-04T09:00:00.000Z", "2026-08-04T09:45:00.000Z",
                        instructor_id=inst["id"], vehicle_id=veh["id"])
    l3 = complete_lesson_at(l3["id"], inst["id"], "2026-08-04T09:45:00.000Z")
    assert l2["instructor_payout_cents"] == 6666   # 3333 * 2.0
    assert l3["instructor_payout_cents"] == 2500   # 3333 * 0.75 == 2499.75 -> 2500


# ===========================================================================
# compensating_invariant / refund_to_wallet_conserves_money
# ===========================================================================
def test_refund_to_wallet_conserves_money(api):
    """PRD §2.9: "Money never appears or disappears outside this ledger: refunds
    enter as positive credits ... the student's `wallet_balance_cents` is
    re-derived from the entries."
    PRD §3.5: "it ... posts a wallet credit — a wallet entry against the student
    for a positive `amount_cents` equal to `refunded_cents`, with `reason`
    `REFUND_CREDIT` and the originating `enrollment_id` — which raises the
    student's `wallet_balance_cents`."

    Design: Difficulty/compensating_invariant/refund_to_wallet_conserves_money
    """
    stu, enr, _pkg, _inst, _veh = _build_enrollment_with_2_road_completed()
    refunded = validate_success(
        api.refund_enrollment(enr["id"],
                              {"refund_method": "PRO_RATA",
                               "refund_destination": "WALLET"}, ADMIN)
    )
    assert refunded["refunded_cents"] == 53333
    student = validate_success(api.get_student(stu["id"], ADMIN))
    assert student["wallet_balance_cents"] == 53333
    # amount_paid 85000 -> (85000 - 53333) recognized + 53333 wallet == 85000.
    assert_money_conserved(85000, refunded["refunded_cents"],
                           student["wallet_balance_cents"])


def test_refund_credit_wallet_entry_recorded(api):
    """PRD §3.5: "posts a wallet credit — a wallet entry against the student for
    a positive `amount_cents` equal to `refunded_cents`, with `reason`
    `REFUND_CREDIT` and the originating `enrollment_id`."

    Design: Difficulty/compensating_invariant/refund_to_wallet_conserves_money
    """
    stu, enr, _pkg, _inst, _veh = _build_enrollment_with_2_road_completed()
    validate_success(
        api.refund_enrollment(enr["id"],
                              {"refund_method": "PRO_RATA",
                               "refund_destination": "WALLET"}, ADMIN)
    )
    entries, _ = validate_paginated(
        api.list_wallet_entries(ADMIN, params={"student_id": stu["id"],
                                               "reason": "REFUND_CREDIT"})
    )
    assert len(entries) == 1
    assert entries[0]["amount_cents"] == 53333
    assert entries[0]["reason"] == "REFUND_CREDIT"
    assert entries[0]["enrollment_id"] == enr["id"]
