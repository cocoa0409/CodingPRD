"""The check-in app: late-pickup fines, CACFP meal reimbursement, duplicate
check-in guard, and teacher ownership.

Translates queue-A difficulty instances (dual_variant CACFP, boundary late-fine,
resource_temporal duplicate-checkin, cross_entity teacher-ownership) and queue-B
corner calculation instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_director_headers, make_teacher_headers, ApiErrorId,
)
import test_helpers.fixtures as fx

DIRECTOR = make_director_headers()


def test_cacfp_tier_i_reimbursement(api):
    """PRD §3.6: "Under TIER_I the per-meal rates are 240 cents for breakfast, 449
    cents for lunch, and 119 cents for snack".

    breakfast=1 lunch=1 snack=1 -> 240+449+119 = 808.

    Design: Difficulty/dual_variant_calc/cacfp_tier_i_vs_tier_ii_reimbursement_divergence
    """
    _, classroom, _, _, _, att = fx.setup_checked_out_day(
        "2026-03-02T09:00:00Z", "2026-03-02T17:00:00Z", "2026-03-02", "17:00",
        center_overrides={"cacfp_tier": "TIER_I"},
        child_overrides={"enrolls_in_cacfp": True},
        meal_overrides={"meals_breakfast": 1, "meals_lunch": 1, "meals_snack": 1})
    assert att["cacfp_reimbursement_cents"] == 808


def test_cacfp_tier_ii_reimbursement_is_strictly_smaller(api):
    """PRD §3.6: "under TIER_II they are 90 cents for breakfast, 271 cents for
    lunch, and 33 cents for snack — so the same meal counts always yield a strictly
    smaller reimbursement under TIER_II than under TIER_I."

    breakfast=1 lunch=1 snack=1 -> 90+271+33 = 394.

    Design: Difficulty/dual_variant_calc/cacfp_tier_i_vs_tier_ii_reimbursement_divergence
    """
    _, classroom, _, _, _, att = fx.setup_checked_out_day(
        "2026-03-02T09:00:00Z", "2026-03-02T17:00:00Z", "2026-03-02", "17:00",
        center_overrides={"cacfp_tier": "TIER_II"},
        child_overrides={"enrolls_in_cacfp": True},
        meal_overrides={"meals_breakfast": 1, "meals_lunch": 1, "meals_snack": 1})
    assert att["cacfp_reimbursement_cents"] == 394


def test_cacfp_tier_i_with_two_snacks(api):
    """PRD §3.6: "the reimbursement is the breakfast count times the breakfast rate
    plus the lunch count times the lunch rate plus the snack count times the snack
    rate. Under TIER_I the per-meal rates are 240 cents for breakfast, 449 cents
    for lunch, and 119 cents for snack".

    b1 l1 s2 -> 240+449+2*119 = 927.

    Design: Corner/calculations/cacfp_tier_i_with_two_snacks
    """
    _, classroom, _, _, _, att = fx.setup_checked_out_day(
        "2026-03-02T16:00:00Z", "2026-03-02T17:00:00Z", "2026-03-02", "17:00",
        center_overrides={"cacfp_tier": "TIER_I"},
        child_overrides={"enrolls_in_cacfp": True},
        meal_overrides={"meals_breakfast": 1, "meals_lunch": 1, "meals_snack": 2})
    assert att["cacfp_reimbursement_cents"] == 927


def test_cacfp_zero_when_child_opted_out(api):
    """PRD §3.6: "If the child's enrolls_in_cacfp is false, the
    cacfp_reimbursement_cents for the day is 0."

    Design: Corner/calculations/cacfp_zero_when_child_opted_out
    """
    _, classroom, _, _, _, att = fx.setup_checked_out_day(
        "2026-03-02T16:00:00Z", "2026-03-02T17:00:00Z", "2026-03-02", "17:00",
        center_overrides={"cacfp_tier": "TIER_I"},
        child_overrides={"enrolls_in_cacfp": False},
        meal_overrides={"meals_breakfast": 1, "meals_lunch": 1, "meals_snack": 2})
    assert att["cacfp_reimbursement_cents"] == 0


def test_late_pickup_exactly_grace_is_free(api):
    """PRD §3.6: "The billable lateness, stored as late_pickup_minutes, is the
    greater of 0 and the raw lateness minus the center's late_pickup_grace_minutes
    — so a child exactly at the grace boundary is billable for 0 minutes and
    incurs no fine."

    grace 5, scheduled 17:00, check-out 17:05 -> raw 5, billable 0, fine 0.

    Design: Difficulty/boundary_precision_check/late_pickup_exactly_grace_is_free_boundary
    """
    _, classroom, _, _, _, att = fx.setup_checked_out_day(
        "2026-03-02T16:00:00Z", "2026-03-02T17:05:00Z", "2026-03-02", "17:00",
        center_overrides={"cacfp_tier": "TIER_I", "late_pickup_grace_minutes": 5,
                          "late_pickup_fee_per_block_cents": 1500,
                          "late_pickup_block_minutes": 15})
    assert att["late_fine_cents"] == 0
    assert att["late_pickup_minutes"] == 0


def test_late_pickup_one_minute_over_grace_charges_one_block(api):
    """PRD §3.6: "when billable lateness is positive, the number of chargeable
    blocks is the billable minutes divided by the center's late_pickup_block_minutes,
    rounded up to the next whole block (so a single minute past grace already starts
    and charges one full block) ... The late_fine_cents is the number of blocks
    multiplied by the center's late_pickup_fee_per_block_cents."

    grace 5, check-out 17:06 -> raw 6, billable 1, ceil(1/15)=1 block, fine 1500.

    Design: Difficulty/boundary_precision_check/late_pickup_exactly_grace_is_free_boundary
    """
    _, classroom, _, _, _, att = fx.setup_checked_out_day(
        "2026-03-02T16:00:00Z", "2026-03-02T17:06:00Z", "2026-03-02", "17:00",
        center_overrides={"cacfp_tier": "TIER_I", "late_pickup_grace_minutes": 5,
                          "late_pickup_fee_per_block_cents": 1500,
                          "late_pickup_block_minutes": 15})
    assert att["late_fine_cents"] == 1500
    assert att["late_pickup_minutes"] == 1


def test_late_pickup_one_block_at_six_minutes_corner(api):
    """PRD §3.6: "so a single minute past grace already starts and charges one full
    block ... The late_fine_cents is the number of blocks multiplied by the
    center's late_pickup_fee_per_block_cents."

    raw 6, grace 5 -> billable 1 -> ceil(1/15)=1 block -> fine 1500.

    Design: Corner/calculations/late_pickup_one_minute_over_grace_charges_one_block
    """
    _, classroom, _, _, _, att = fx.setup_checked_out_day(
        "2026-03-02T16:00:00Z", "2026-03-02T17:06:00Z", "2026-03-02", "17:00",
        center_overrides={"cacfp_tier": "TIER_I", "late_pickup_grace_minutes": 5,
                          "late_pickup_fee_per_block_cents": 1500,
                          "late_pickup_block_minutes": 15})
    assert att["late_fine_cents"] == 1500
    assert att["late_pickup_minutes"] == 1


def test_late_pickup_two_blocks_at_16_billable_minutes(api):
    """PRD §3.6: "the number of chargeable blocks is the billable minutes divided
    by the center's late_pickup_block_minutes, rounded up to the next whole block".

    grace 5, check-out 17:21 -> raw 21, billable 16, ceil(16/15)=2 blocks,
    fine 3000.

    Design: Corner/calculations/late_pickup_two_blocks_at_16_minutes_billable
    """
    _, classroom, _, _, _, att = fx.setup_checked_out_day(
        "2026-03-02T16:00:00Z", "2026-03-02T17:21:00Z", "2026-03-02", "17:00",
        center_overrides={"cacfp_tier": "TIER_I", "late_pickup_grace_minutes": 5,
                          "late_pickup_fee_per_block_cents": 1500,
                          "late_pickup_block_minutes": 15})
    assert att["late_fine_cents"] == 3000
    assert att["late_pickup_minutes"] == 16


def test_duplicate_checkin_same_enrollment_same_day_rejected(api):
    """PRD §3.6: "At most one CHECKED_IN attendance record may exist per enrollment
    per service date; a second is rejected with ERR_ALREADY_CHECKED_IN."

    Design: Difficulty/resource_temporal_overlap/duplicate_checkin_same_enrollment_same_day_rejected
    """
    fx.set_clock("2026-03-02T08:00:00Z")
    center, classroom, family, child, enrollment = fx.setup_single_active_enrollment()
    fx.create_attendance(classroom, enrollment, "2026-03-02", "17:00")
    teacher = make_teacher_headers(classroom["id"])
    resp = api.create_attendance(
        {"enrollment_id": enrollment["id"], "service_date": "2026-03-02",
         "scheduled_pickup_local": "18:00"}, teacher)
    validate_error(resp, ApiErrorId.ERR_ALREADY_CHECKED_IN.value)


def test_first_checkin_remains_checked_in_after_duplicate_attempt(api):
    """PRD §3.6: "At most one CHECKED_IN attendance record may exist per enrollment
    per service date; a second is rejected with ERR_ALREADY_CHECKED_IN."
    PRD §3.6: "The record is created in the CHECKED_IN state with check_in_at set to
    the current UTC instant".

    The original CHECKED_IN record is preserved (the second create does not
    displace it).

    Design: Difficulty/resource_temporal_overlap/duplicate_checkin_same_enrollment_same_day_rejected
    """
    fx.set_clock("2026-03-02T08:00:00Z")
    center, classroom, family, child, enrollment = fx.setup_single_active_enrollment()
    first = fx.create_attendance(classroom, enrollment, "2026-03-02", "17:00")
    teacher = make_teacher_headers(classroom["id"])
    api.create_attendance(
        {"enrollment_id": enrollment["id"], "service_date": "2026-03-02",
         "scheduled_pickup_local": "18:00"}, teacher)
    still = get_success_data(api.get_attendance(first["id"], teacher))
    assert still["status"] == "CHECKED_IN"


def test_attendance_create_by_non_owning_teacher_rejected(api):
    """PRD §2.1: "When X-User-Role is Teacher, X-User-ID is the id of the acting
    Classroom; ownership checks on any attendance resource compare the classroom of
    the record's enrollment to X-User-ID, and a mismatch is likewise rejected with
    ERR_NOT_RESOURCE_OWNER."

    Design: Difficulty/cross_entity_state_dependency/attendance_checkout_depends_on_enrollment_active_state
    """
    center, classroom, family, child, enrollment = fx.setup_single_active_enrollment()
    other_room = fx.create_classroom(center["id"], name="R2")
    wrong_teacher = make_teacher_headers(other_room["id"])
    resp = api.create_attendance(
        {"enrollment_id": enrollment["id"], "service_date": "2026-03-02",
         "scheduled_pickup_local": "17:00"}, wrong_teacher)
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


def test_attendance_create_by_owning_teacher_succeeds(api):
    """PRD §3.6: "A teacher records a child's arrival through the check-in app,
    creating an AttendanceRecord for one service day. ... The record is created in
    the CHECKED_IN state with check_in_at set to the current UTC instant".
    PRD §2.1: "ownership checks on any attendance resource compare the classroom of
    the record's enrollment to X-User-ID".

    Design: Difficulty/cross_entity_state_dependency/attendance_checkout_depends_on_enrollment_active_state
    """
    fx.set_clock("2026-03-02T08:00:00Z")
    center, classroom, family, child, enrollment = fx.setup_single_active_enrollment()
    teacher = make_teacher_headers(classroom["id"])
    resp = api.create_attendance(
        {"enrollment_id": enrollment["id"], "service_date": "2026-03-02",
         "scheduled_pickup_local": "17:00"}, teacher)
    data = validate_success(resp, 201)
    assert data["status"] == "CHECKED_IN"
