"""Validation-precedence conflicts, ratio/capacity boundary precision, cross-entity state
dependencies, and the contrasting temporal-overlap interval semantics
(PRD §2.8, §2.10, §3.4, §3.12).

Each test translates exactly one design-index instance.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    accept_offer_payload, create_payment_payload,
    end_staff_assignment_payload, create_observation_payload,
    set_clock, create_tier, create_classroom, create_room_with_staff, assign_staff,
    create_student, enroll_child, application_under_review, application_offered,
    application_waitlisted, capture_deposit,
    setup_enrolled_child, setup_room_at_placed_count, open_slot, book_slot,
    make_parent_headers, make_guide_headers, TEST_USERS, api_client,
)

REGISTRAR = TEST_USERS["registrar_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ─── priority_pair_validation_conflict / offer_compliance_beats_full ───────────

def test_offer_non_compliant_and_full_returns_not_compliant(api):
    """PRD §2.10: "The remaining business validations follow in this order: tier/level
    mismatch (ERR_TIER_LEVEL_MISMATCH), age out of range (ERR_AGE_OUT_OF_RANGE), classroom
    not compliant (ERR_CLASSROOM_NOT_COMPLIANT), guide double-booking
    (ERR_GUIDE_DOUBLE_BOOKED), observation overlap (ERR_OBSERVATION_OVERLAP), invalid
    interval (ERR_INVALID_INTERVAL), classroom full (ERR_CLASSROOM_FULL), deposit amount
    mismatch (ERR_DEPOSIT_AMOUNT_MISMATCH), and refund eligibility (ERR_REFUND_NOT_ELIGIBLE)."
    PRD §2.8: "an attempt to place a child into a room that is not COMPLIANT is rejected with
    ERR_CLASSROOM_NOT_COMPLIANT."

    Design: Difficulty/priority_pair_validation_conflict/offer_compliance_beats_full_safety_vs_constraint
    """
    set_clock("2026-09-01T00:00:00Z")
    tier = create_tier(code="STD", level="PRIMARY", base_annual_cents=1_000_000,
                       deposit_pct=0.10, installments=10)
    room = create_classroom(name="Primary I", level="PRIMARY", capacity=1)
    sa = assign_staff(room["id"], room["version"], "Maria")
    room = get_success_data(api.get_classroom(room["id"], COMPLIANCE))

    # Fill the single seat (placed_count == capacity == 1).
    stu_a = create_student(parent_user_id="parent-a", full_name="Child A")
    enroll_child(stu_a["id"], room["id"], tier["id"], parent_user_id="parent-a")

    # Child B under review.
    stu_b = create_student(parent_user_id="parent-b", full_name="Child B")
    app_b = application_under_review(stu_b["id"], room["id"], tier["id"],
                                     parent_user_id="parent-b")

    # End the only staff assignment so required_staff(1)=1 > 0 ACTIVE => OVER_RATIO.
    room = get_success_data(api.get_classroom(room["id"], COMPLIANCE))
    validate_success(api.end_staff_assignment(
        sa["id"], end_staff_assignment_payload(room["version"]), COMPLIANCE), 200)
    room = get_success_data(api.get_classroom(room["id"], COMPLIANCE))
    assert room["compliance_status"] == "OVER_RATIO"

    # Offer B: room is BOTH full and non-compliant. Compliance wins.
    res = api.offer(app_b["id"], REGISTRAR)
    validate_error(res, "ERR_CLASSROOM_NOT_COMPLIANT", expected_status=409)


# ─── boundary_precision_check / ratio_boundary_exact_vs_plus_one_over_ratio ────

def test_ratio_boundary_eleventh_placement_tips_over_ratio(api):
    """PRD §2.8: "a room whose placed_count exactly equals the level cap times its staff
    count is COMPLIANT while one more placed child than that tips it to OVER_RATIO."

    Design: Difficulty/boundary_precision_check/ratio_boundary_exact_vs_plus_one_over_ratio
    """
    # 10 placed in PRIMARY with 1 staff (cap 10) => COMPLIANT exactly at the boundary.
    room, tier, enr_ids = setup_room_at_placed_count(
        level="PRIMARY", capacity=20, placed=10, staff=1)
    assert room["placed_count"] == 10
    assert room["compliance_status"] == "COMPLIANT"

    # 11th accept-offer tips it to OVER_RATIO (ceil(11/10)=2 > 1 staff).
    stu = create_student(parent_user_id="parent-11", full_name="Eleventh")
    enroll_child(stu["id"], room["id"], tier["id"], parent_user_id="parent-11",
                 program_start_date="2026-09-01T00:00:00Z")
    room_after = get_success_data(api.get_classroom(room["id"], REGISTRAR))
    assert room_after["placed_count"] == 11, f"got {room_after['placed_count']}"
    assert room_after["compliance_status"] == "OVER_RATIO", (
        f"got {room_after['compliance_status']}")


def test_ratio_over_ratio_blocks_next_offer(api):
    """PRD §2.8: "A room must be COMPLIANT for a child to be offered a seat, to accept an
    offer, to return from leave, or to be promoted off the waitlist; an attempt to place a
    child into a room that is not COMPLIANT is rejected with ERR_CLASSROOM_NOT_COMPLIANT."

    Design: Difficulty/boundary_precision_check/ratio_boundary_exact_vs_plus_one_over_ratio
    """
    room, tier, enr_ids = setup_room_at_placed_count(
        level="PRIMARY", capacity=20, placed=10, staff=1)
    # Place the 11th to reach OVER_RATIO.
    stu = create_student(parent_user_id="parent-11", full_name="Eleventh")
    enroll_child(stu["id"], room["id"], tier["id"], parent_user_id="parent-11")
    room_after = get_success_data(api.get_classroom(room["id"], REGISTRAR))
    assert room_after["compliance_status"] == "OVER_RATIO"

    # A 12th offer attempt is rejected for non-compliance.
    stu12 = create_student(parent_user_id="parent-12", full_name="Twelfth")
    app12 = application_under_review(stu12["id"], room["id"], tier["id"],
                                     parent_user_id="parent-12")
    res = api.offer(app12["id"], REGISTRAR)
    validate_error(res, "ERR_CLASSROOM_NOT_COMPLIANT", expected_status=409)


# ─── boundary_precision_check / capacity_boundary_full_exact_count ─────────────

def test_capacity_full_offer_rejected(api):
    """PRD §3.4: "A placement attempt into a room that is full is rejected with
    ERR_CLASSROOM_FULL".

    Design: Difficulty/boundary_precision_check/capacity_boundary_full_exact_count_empty_seat
    """
    set_clock("2026-09-01T00:00:00Z")
    tier = create_tier(code="STD", level="PRIMARY", base_annual_cents=1_000_000,
                       deposit_pct=0.10, installments=10)
    room, _ = create_room_with_staff(level="PRIMARY", capacity=1, staff=1, name="Primary L")

    stu_a = create_student(parent_user_id="parent-a", full_name="Child A")
    enroll_child(stu_a["id"], room["id"], tier["id"], parent_user_id="parent-a")
    room_full = get_success_data(api.get_classroom(room["id"], REGISTRAR))
    assert room_full["placed_count"] == 1  # == capacity

    stu_b = create_student(parent_user_id="parent-b", full_name="Child B")
    app_b = application_under_review(stu_b["id"], room["id"], tier["id"],
                                     parent_user_id="parent-b")
    res = api.offer(app_b["id"], REGISTRAR)
    validate_error(res, "ERR_CLASSROOM_FULL", expected_status=409)


def test_capacity_below_full_offer_succeeds(api):
    """PRD §3.4: "A registrar may offer a seat directly out of review, transitioning the
    application UNDER_REVIEW → OFFERED, when the room is COMPLIANT, the room has a free seat
    (its placed_count is strictly less than its capacity), and the student's age in months
    falls within the room's inclusive age band."

    Design: Difficulty/boundary_precision_check/capacity_boundary_full_exact_count_empty_seat
    """
    set_clock("2026-09-01T00:00:00Z")
    tier = create_tier(code="STD", level="PRIMARY", base_annual_cents=1_000_000,
                       deposit_pct=0.10, installments=10)
    # capacity 1, 0 placed => placed_count (0) < capacity (1): an offer succeeds.
    room, _ = create_room_with_staff(level="PRIMARY", capacity=1, staff=1, name="Primary L2")
    stu = create_student(parent_user_id="parent-a", full_name="Child A")
    app = application_under_review(stu["id"], room["id"], tier["id"],
                                   parent_user_id="parent-a")
    offered = validate_success(api.offer(app["id"], REGISTRAR), 200)
    assert offered["status"] == "OFFERED", f"got {offered['status']}"


# ─── cross_entity_state_dependency / offer_requires_classroom_compliant ────────

def test_offer_blocked_when_classroom_over_ratio(api):
    """PRD §3.4: "into a room that is not compliant, with ERR_CLASSROOM_NOT_COMPLIANT."
    PRD §2.8: "A room must be COMPLIANT for a child to be offered a seat".

    Design: Difficulty/cross_entity_state_dependency/offer_requires_classroom_compliant_application_to_classroom
    """
    set_clock("2026-09-01T00:00:00Z")
    tier = create_tier(code="STD", level="PRIMARY", base_annual_cents=1_000_000,
                       deposit_pct=0.10, installments=10)
    room = create_classroom(name="Primary M", level="PRIMARY", capacity=5)
    sa = assign_staff(room["id"], room["version"], "Maria")
    room = get_success_data(api.get_classroom(room["id"], COMPLIANCE))

    # Place one child so placed_count == 1.
    stu_a = create_student(parent_user_id="parent-a", full_name="Child A")
    enroll_child(stu_a["id"], room["id"], tier["id"], parent_user_id="parent-a")

    # End the staff so required_staff(1)=1 > 0 ACTIVE => OVER_RATIO.
    room = get_success_data(api.get_classroom(room["id"], COMPLIANCE))
    validate_success(api.end_staff_assignment(
        sa["id"], end_staff_assignment_payload(room["version"]), COMPLIANCE), 200)
    room = get_success_data(api.get_classroom(room["id"], COMPLIANCE))
    assert room["compliance_status"] == "OVER_RATIO"

    # Second child cannot be offered while the room is non-compliant.
    stu_b = create_student(parent_user_id="parent-b", full_name="Child B")
    app_b = application_under_review(stu_b["id"], room["id"], tier["id"],
                                     parent_user_id="parent-b")
    res = api.offer(app_b["id"], REGISTRAR)
    validate_error(res, "ERR_CLASSROOM_NOT_COMPLIANT", expected_status=409)


# ─── resource_temporal_overlap / guide_double_book_half_open ───────────────────

def test_adjacent_slot_books_half_open_no_overlap(api):
    """PRD §3.12: "if any other slot for the same guide_user_id whose half-open interval
    from start_at (inclusive) to end_at (exclusive) overlaps this slot is already BOOKED,
    the booking is rejected with ERR_GUIDE_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/guide_double_book_half_open_overlap
    """
    set_clock("2026-09-01T00:00:00Z")
    tier = create_tier(code="STD", level="PRIMARY", base_annual_cents=1_000_000,
                       deposit_pct=0.10, installments=10)
    room, _ = create_room_with_staff(level="PRIMARY", capacity=5, staff=1, name="Primary O")
    stu = create_student(parent_user_id="parent-1", full_name="Kid One")
    enroll_child(stu["id"], room["id"], tier["id"], parent_user_id="parent-1")

    slot_a = open_slot(room["id"], guide_user_id="guide-1",
                       start_at="2026-10-01T15:00:00Z", end_at="2026-10-01T15:30:00Z")
    book_slot(slot_a["id"], stu["id"], parent_user_id="parent-1")

    # Adjacent 15:30-16:00 shares only the exclusive endpoint => no overlap, books OK.
    slot_adj = open_slot(room["id"], guide_user_id="guide-1",
                         start_at="2026-10-01T15:30:00Z", end_at="2026-10-01T16:00:00Z")
    from test_helpers import book_slot_payload
    res = api.book_slot(slot_adj["id"], book_slot_payload(stu["id"]),
                        make_parent_headers("parent-1"))
    booked = validate_success(res, 200)
    assert booked["status"] == "BOOKED", f"got {booked['status']}"


def test_overlapping_slot_double_booked_rejected(api):
    """PRD §3.12: "if any other slot for the same guide_user_id whose half-open interval
    from start_at (inclusive) to end_at (exclusive) overlaps this slot is already BOOKED,
    the booking is rejected with ERR_GUIDE_DOUBLE_BOOKED."

    Design: Difficulty/resource_temporal_overlap/guide_double_book_half_open_overlap
    """
    set_clock("2026-09-01T00:00:00Z")
    tier = create_tier(code="STD", level="PRIMARY", base_annual_cents=1_000_000,
                       deposit_pct=0.10, installments=10)
    room, _ = create_room_with_staff(level="PRIMARY", capacity=5, staff=1, name="Primary O2")
    stu = create_student(parent_user_id="parent-1", full_name="Kid One")
    enroll_child(stu["id"], room["id"], tier["id"], parent_user_id="parent-1")

    slot_a = open_slot(room["id"], guide_user_id="guide-1",
                       start_at="2026-10-01T15:00:00Z", end_at="2026-10-01T15:30:00Z")
    book_slot(slot_a["id"], stu["id"], parent_user_id="parent-1")

    # Overlapping 15:15-15:45 collides with the BOOKED 15:00-15:30.
    slot_ovl = open_slot(room["id"], guide_user_id="guide-1",
                         start_at="2026-10-01T15:15:00Z", end_at="2026-10-01T15:45:00Z")
    from test_helpers import book_slot_payload
    res = api.book_slot(slot_ovl["id"], book_slot_payload(stu["id"]),
                        make_parent_headers("parent-1"))
    validate_error(res, "ERR_GUIDE_DOUBLE_BOOKED", expected_status=409)


# ─── resource_temporal_overlap / observation_closed_interval_shared_endpoint ───

def test_observation_shared_endpoint_conflicts_closed_interval(api):
    """PRD §3.12: "the overlap test here is a closed interval: two windows that merely share
    an endpoint do conflict. A window that overlaps another window for the same classroom_id
    is rejected with ERR_OBSERVATION_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/observation_closed_interval_shared_endpoint_conflicts
    """
    room = create_classroom(name="Primary P", level="PRIMARY", capacity=5)
    validate_success(api.create_observation(
        create_observation_payload(room["id"], "Visitor A",
                                   "2026-10-01T15:00:00Z", "2026-10-01T15:30:00Z"),
        COMPLIANCE), 201)

    # Window 15:30-16:00 shares only the 15:30 endpoint, but closed-interval => conflict.
    res = api.create_observation(
        create_observation_payload(room["id"], "Visitor B",
                                   "2026-10-01T15:30:00Z", "2026-10-01T16:00:00Z"),
        COMPLIANCE)
    validate_error(res, "ERR_OBSERVATION_OVERLAP", expected_status=409)


def test_observation_strictly_overlapping_window_rejected(api):
    """PRD §3.12: "A window that overlaps another window for the same classroom_id is
    rejected with ERR_OBSERVATION_OVERLAP."

    Design: Difficulty/resource_temporal_overlap/observation_closed_interval_shared_endpoint_conflicts
    """
    room = create_classroom(name="Primary P2", level="PRIMARY", capacity=5)
    validate_success(api.create_observation(
        create_observation_payload(room["id"], "Visitor A",
                                   "2026-10-01T15:00:00Z", "2026-10-01T15:30:00Z"),
        COMPLIANCE), 201)
    # Window 15:15-15:45 genuinely overlaps the existing 15:00-15:30 window.
    res = api.create_observation(
        create_observation_payload(room["id"], "Visitor B",
                                   "2026-10-01T15:15:00Z", "2026-10-01T15:45:00Z"),
        COMPLIANCE)
    validate_error(res, "ERR_OBSERVATION_OVERLAP", expected_status=409)


# ─── second tests for cross-entity / priority instances ────────────────────────

def test_book_succeeds_when_student_has_placed_enrollment(api):
    """PRD §3.12: "the acting parent must own the named student, and that student must have
    an enrollment in PLACED placement status in the slot's classroom_id."

    Design: Difficulty/cross_entity_state_dependency/book_requires_student_placed_enrollment_slot_to_enrollment
    """
    set_clock("2026-09-01T00:00:00Z")
    tier = create_tier(code="STD", level="PRIMARY", base_annual_cents=1_000_000,
                       deposit_pct=0.10, installments=10)
    room, _ = create_room_with_staff(level="PRIMARY", capacity=5, staff=1, name="Primary N2")
    # Child has a PLACED enrollment in the room.
    stu = create_student(parent_user_id="parent-1", full_name="Placed Kid")
    enroll_child(stu["id"], room["id"], tier["id"], parent_user_id="parent-1")
    slot = open_slot(room["id"], guide_user_id="guide-1",
                     start_at="2026-10-01T15:00:00Z", end_at="2026-10-01T15:30:00Z")
    booked = book_slot(slot["id"], stu["id"], parent_user_id="parent-1")
    assert booked["status"] == "BOOKED", f"got {booked['status']}"
    assert booked["booked_student_id"] == stu["id"]


def test_offer_succeeds_when_classroom_compliant(api):
    """PRD §3.4: "A registrar may offer a seat directly out of review, transitioning the
    application UNDER_REVIEW → OFFERED, when the room is COMPLIANT, the room has a free seat
    (its placed_count is strictly less than its capacity), and the student's age in months
    falls within the room's inclusive age band."

    Design: Difficulty/cross_entity_state_dependency/offer_requires_classroom_compliant_application_to_classroom
    """
    set_clock("2026-09-01T00:00:00Z")
    tier = create_tier(code="STD", level="PRIMARY", base_annual_cents=1_000_000,
                       deposit_pct=0.10, installments=10)
    # Compliant staffed room with a free seat.
    room, _ = create_room_with_staff(level="PRIMARY", capacity=5, staff=1, name="Primary M2")
    room_now = get_success_data(api.get_classroom(room["id"], COMPLIANCE))
    assert room_now["compliance_status"] == "COMPLIANT"
    stu = create_student(parent_user_id="parent-1", full_name="Child")
    app = application_under_review(stu["id"], room["id"], tier["id"],
                                   parent_user_id="parent-1")
    offered = validate_success(api.offer(app["id"], REGISTRAR), 200)
    assert offered["status"] == "OFFERED", f"got {offered['status']}"


def test_wrong_amount_deposit_while_deposit_due_returns_amount_mismatch(api):
    """PRD §3.7: "its amount_cents must equal the enrollment's deposit_cents exactly; a
    deposit posted at the wrong time or for the wrong amount is rejected with
    ERR_DEPOSIT_AMOUNT_MISMATCH."

    Design: Difficulty/priority_pair_validation_conflict/deposit_state_beats_amount_state_vs_fiscal
    """
    # While still DEPOSIT_DUE the deposit transition IS defined, so the wrong amount falls
    # through to the fiscal check (the loser path of the state-vs-fiscal precedence).
    room, tier, student, enr = setup_enrolled_child(
        base_annual_cents=1_000_000, deposit_pct=0.10, installments=10)
    assert enr["billing_status"] == "DEPOSIT_DUE"
    res = api.create_payment(
        create_payment_payload(enr["id"], "DEPOSIT", 99999), REGISTRAR)
    validate_error(res, "ERR_DEPOSIT_AMOUNT_MISMATCH", expected_status=422)


def test_offer_full_but_compliant_returns_classroom_full(api):
    """PRD §3.4: "A placement attempt into a room that is full is rejected with
    ERR_CLASSROOM_FULL".
    PRD §2.8: "a room whose placed_count equals its capacity is COMPLIANT (capacity is
    breached only when placed children exceed capacity, not when they equal it)".

    Design: Difficulty/priority_pair_validation_conflict/offer_compliance_beats_full_safety_vs_constraint
    """
    set_clock("2026-09-01T00:00:00Z")
    tier = create_tier(code="STD", level="PRIMARY", base_annual_cents=1_000_000,
                       deposit_pct=0.10, installments=10)
    # capacity 1, 1 staff: placing 1 child leaves placed_count==capacity==1 and COMPLIANT
    # (ceil(1/10)=1 staff required, 1 active). Room is full but compliant.
    room, _ = create_room_with_staff(level="PRIMARY", capacity=1, staff=1, name="Primary I2")
    stu_a = create_student(parent_user_id="parent-a", full_name="Child A")
    enroll_child(stu_a["id"], room["id"], tier["id"], parent_user_id="parent-a")
    room_full = get_success_data(api.get_classroom(room["id"], COMPLIANCE))
    assert room_full["placed_count"] == 1
    assert room_full["compliance_status"] == "COMPLIANT"

    stu_b = create_student(parent_user_id="parent-b", full_name="Child B")
    app_b = application_under_review(stu_b["id"], room["id"], tier["id"],
                                     parent_user_id="parent-b")
    # Compliance check passes (COMPLIANT), so the full check fires.
    res = api.offer(app_b["id"], REGISTRAR)
    validate_error(res, "ERR_CLASSROOM_FULL", expected_status=409)
