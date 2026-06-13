"""Master scheduling: seating, period exclusivity, capacity, and seat-count
conservation.

Covers difficulty instances under priority_pair_validation_conflict,
resource_temporal_overlap, cross_entity_state_dependency, transitive_cascade,
compensating_invariant, plus corner instances on enrolled_count.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    assert_section,
    fixtures as fx,
)

REG = TEST_USERS["registrar_headers"]


# ---------------------------------------------------------------------------
# resource_temporal_overlap / section_period_point_exclusivity_overlap
# ---------------------------------------------------------------------------
def test_period_conflict_two_sections_same_period_rejected(api):
    """PRD §3.4: "an enrollment may not hold two ENROLLED assignments meeting in
    the same period, and an attempt to do so is rejected with
    ERR_SCHEDULE_PERIOD_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/section_period_point_exclusivity_overlap
    """
    school = fx.create_school()
    student = fx.create_student(school["id"])
    enr = fx.create_enrollment(student["id"])
    course = fx.create_course(school["id"])
    sec1 = fx.create_section(course["id"], period=1, teacher_user_id="teacher-1")
    sec1b = fx.create_section(course["id"], period=1, teacher_user_id="teacher-2")
    fx.seat(enr["id"], sec1["id"])
    resp = api.create_schedule_assignment(
        {"enrollment_id": enr["id"], "section_id": sec1b["id"]}, REG)
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_PERIOD_CONFLICT.value, expected_status=409)
    refreshed = validate_success(api.get_section(sec1b["id"], REG))
    assert refreshed["enrolled_count"] == 0, "no seat created on the conflicting section"


def test_period_conflict_blocks_even_when_target_section_open(api):
    """PRD §3.4: "an enrollment may not hold two ENROLLED assignments meeting in
    the same period, and an attempt to do so is rejected with
    ERR_SCHEDULE_PERIOD_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/section_period_point_exclusivity_overlap
    """
    school = fx.create_school()
    student = fx.create_student(school["id"])
    enr = fx.create_enrollment(student["id"])
    course = fx.create_course(school["id"])
    secA = fx.create_section(course["id"], period=3)
    secB = fx.create_section(course["id"], period=3)
    fx.seat(enr["id"], secA["id"])
    resp = api.create_schedule_assignment(
        {"enrollment_id": enr["id"], "section_id": secB["id"]}, REG)
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_PERIOD_CONFLICT.value, expected_status=409)


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / schedule_period_conflict_vs_capacity_priority
# ---------------------------------------------------------------------------
def test_period_conflict_wins_over_capacity_when_both_violated(api):
    """PRD §3.4: "First, the enrollment must be ACTIVE and the section OPEN, or the
    create is rejected with ERR_PARENT_NOT_ACTIVE. Second, the seat must not create
    a period collision: an enrollment may not hold two ENROLLED assignments meeting
    in the same period, and an attempt to do so is rejected with
    ERR_SCHEDULE_PERIOD_CONFLICT. Third, the section's capacity is period-independent
    — the count of ENROLLED assignments must not exceed the section's capacity, and
    an overflow is rejected with ERR_SECTION_CAPACITY_EXCEEDED."

    Design: Difficulty/priority_pair_validation_conflict/schedule_period_conflict_vs_capacity_priority
    """
    school = fx.create_school()
    course = fx.create_course(school["id"])
    studentA = fx.create_student(school["id"])
    studentB = fx.create_student(school["id"])
    enrA = fx.create_enrollment(studentA["id"])
    enrB = fx.create_enrollment(studentB["id"])
    sec_full = fx.create_section(course["id"], period=1, capacity=1, teacher_user_id="teacher-1")
    sec_other = fx.create_section(course["id"], period=1, capacity=30, teacher_user_id="teacher-2")
    fx.seat(enrB["id"], sec_full["id"])      # sec_full now at capacity (1/1)
    fx.seat(enrA["id"], sec_other["id"])     # enrA now holds a period-1 seat
    # enrA -> sec_full: both period collision AND capacity overflow apply.
    resp = api.create_schedule_assignment(
        {"enrollment_id": enrA["id"], "section_id": sec_full["id"]}, REG)
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_PERIOD_CONFLICT.value, expected_status=409)
    refreshed = validate_success(api.get_section(sec_full["id"], REG))
    assert refreshed["enrolled_count"] == 1, "full section's enrolled_count unchanged"


def test_capacity_exceeded_when_only_capacity_violated(api):
    """PRD §3.4: "the count of ENROLLED assignments must not exceed the section's
    capacity, and an overflow is rejected with ERR_SECTION_CAPACITY_EXCEEDED."

    Design: Difficulty/priority_pair_validation_conflict/schedule_period_conflict_vs_capacity_priority
    """
    school = fx.create_school()
    course = fx.create_course(school["id"])
    studentA = fx.create_student(school["id"])
    studentB = fx.create_student(school["id"])
    enrA = fx.create_enrollment(studentA["id"])
    enrB = fx.create_enrollment(studentB["id"])
    sec_full = fx.create_section(course["id"], period=1, capacity=1)
    fx.seat(enrB["id"], sec_full["id"])   # fills capacity; enrA holds no period-1 seat
    resp = api.create_schedule_assignment(
        {"enrollment_id": enrA["id"], "section_id": sec_full["id"]}, REG)
    validate_error(resp, ApiErrorId.ERR_SECTION_CAPACITY_EXCEEDED.value, expected_status=409)


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / schedule_assignment_requires_enrollment_active_and_section_open
# ---------------------------------------------------------------------------
def test_seat_into_closed_section_rejected(api):
    """PRD §3.4: "the enrollment must be ACTIVE and the section OPEN, or the create
    is rejected with ERR_PARENT_NOT_ACTIVE."
    PRD §3.4: "A CLOSED section rejects them."

    Design: Difficulty/cross_entity_state_dependency/schedule_assignment_requires_enrollment_active_and_section_open
    """
    school = fx.create_school()
    student = fx.create_student(school["id"])
    enr = fx.create_enrollment(student["id"])
    course = fx.create_course(school["id"])
    section = fx.create_section(course["id"], period=1)
    validate_success(api.close_section(section["id"], REG))
    resp = api.create_schedule_assignment(
        {"enrollment_id": enr["id"], "section_id": section["id"]}, REG)
    # A closed section is not OPEN; seating against it is ERR_PARENT_NOT_ACTIVE per §3.4.
    validate_error(resp, ApiErrorId.ERR_PARENT_NOT_ACTIVE.value, expected_status=409)
    refreshed = validate_success(api.get_section(section["id"], REG))
    assert refreshed["enrolled_count"] == 0, "no seat created against a closed section"


def test_seat_against_withdrawn_enrollment_rejected(api):
    """PRD §3.4: "the enrollment must be ACTIVE and the section OPEN, or the create
    is rejected with ERR_PARENT_NOT_ACTIVE."

    Design: Difficulty/cross_entity_state_dependency/schedule_assignment_requires_enrollment_active_and_section_open
    """
    ctx = fx.setup_enrolled_student(clock_days=2)
    course = fx.create_course(ctx["school"]["id"])
    section = fx.create_section(course["id"], period=1)
    validate_success(api.withdraw_enrollment(ctx["enrollment"]["id"], {"exit_day_index": 2}, REG))
    resp = api.create_schedule_assignment(
        {"enrollment_id": ctx["enrollment"]["id"], "section_id": section["id"]}, REG)
    validate_error(resp, ApiErrorId.ERR_PARENT_NOT_ACTIVE.value, expected_status=409)


# ---------------------------------------------------------------------------
# transitive_cascade / withdraw_cascade_depth2_section_enrolled_count
# ---------------------------------------------------------------------------
def test_withdraw_drops_schedule_and_decrements_enrolled_count(api):
    """PRD §3.3: "Every schedule assignment of this enrollment still in ENROLLED
    status is moved to DROPPED, and each affected section's enrolled_count is
    decremented by one."

    Design: Difficulty/transitive_cascade/withdraw_cascade_depth2_section_enrolled_count
    """
    school = fx.create_school()
    fx.advance_clock(school["id"], 2)
    student = fx.create_student(school["id"])
    enr = fx.create_enrollment(student["id"])
    course = fx.create_course(school["id"])
    sec1 = fx.create_section(course["id"], period=1)
    sec2 = fx.create_section(course["id"], period=2)
    fx.seat(enr["id"], sec1["id"])
    fx.seat(enr["id"], sec2["id"])
    withdrawn = validate_success(api.withdraw_enrollment(enr["id"], {"exit_day_index": 2}, REG))
    assert withdrawn["status"] == "WITHDRAWN"
    assigns, _ = api_list_assignments(api, enr["id"])
    assert all(a["status"] == "DROPPED" for a in assigns), "all assignments dropped"
    assert validate_success(api.get_section(sec1["id"], REG))["enrolled_count"] == 0
    assert validate_success(api.get_section(sec2["id"], REG))["enrolled_count"] == 0


def test_withdraw_cascade_returns_terminal_enrollment(api):
    """PRD §3.3: "On a valid withdrawal the enrollment moves ACTIVE → WITHDRAWN, its
    exit_day_index is set from the body".

    Design: Difficulty/transitive_cascade/withdraw_cascade_depth2_section_enrolled_count
    """
    school = fx.create_school()
    fx.advance_clock(school["id"], 2)
    student = fx.create_student(school["id"])
    enr = fx.create_enrollment(student["id"])
    course = fx.create_course(school["id"])
    sec1 = fx.create_section(course["id"], period=1)
    fx.seat(enr["id"], sec1["id"])
    withdrawn = validate_success(api.withdraw_enrollment(enr["id"], {"exit_day_index": 2}, REG))
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["exit_day_index"] == 2
    assert validate_success(api.get_section(sec1["id"], REG))["enrolled_count"] == 0


# ---------------------------------------------------------------------------
# compensating_invariant / seat_then_drop_preserves_section_enrolled_count
# ---------------------------------------------------------------------------
def test_seat_then_drop_restores_enrolled_count(api):
    """PRD §3.4: "A registrar may drop an assignment, moving its status ENROLLED →
    DROPPED and decrementing the section's enrolled_count by one."

    Design: Difficulty/compensating_invariant/seat_then_drop_preserves_section_enrolled_count
    """
    school = fx.create_school()
    student = fx.create_student(school["id"])
    enr = fx.create_enrollment(student["id"])
    course = fx.create_course(school["id"])
    section = fx.create_section(course["id"], period=1, capacity=30)
    sa = fx.seat(enr["id"], section["id"])
    assert validate_success(api.get_section(section["id"], REG))["enrolled_count"] == 1
    dropped = validate_success(api.drop_schedule_assignment(sa["id"], REG))
    assert dropped["status"] == "DROPPED"
    assert validate_success(api.get_section(section["id"], REG))["enrolled_count"] == 0, \
        "enrolled_count restored to pre-seat value 0"


def test_drop_sets_assignment_dropped(api):
    """PRD §3.4: "A registrar may drop an assignment, moving its status ENROLLED →
    DROPPED and decrementing the section's enrolled_count by one."

    Design: Difficulty/compensating_invariant/seat_then_drop_preserves_section_enrolled_count
    """
    school = fx.create_school()
    student = fx.create_student(school["id"])
    enr = fx.create_enrollment(student["id"])
    course = fx.create_course(school["id"])
    section = fx.create_section(course["id"], period=2, capacity=30)
    sa = fx.seat(enr["id"], section["id"])
    dropped = validate_success(api.drop_schedule_assignment(sa["id"], REG))
    assert dropped["status"] == "DROPPED"


# ---------------------------------------------------------------------------
# corner: derived_enrolled_count_increments_on_seat
# ---------------------------------------------------------------------------
def test_enrolled_count_increments_on_seat(api):
    """PRD §3.4: "A new assignment starts ENROLLED, copies the section's period onto
    itself, and increments the section's enrolled_count by one."

    Design: Corner/cross_cutting_complexity_layers/derived_enrolled_count_increments_on_seat
    """
    school = fx.create_school()
    student = fx.create_student(school["id"])
    enr = fx.create_enrollment(student["id"])
    course = fx.create_course(school["id"])
    section = fx.create_section(course["id"], period=1, capacity=30)
    fx.seat(enr["id"], section["id"])
    refreshed = validate_success(api.get_section(section["id"], REG))
    assert refreshed["enrolled_count"] == 1, f"enrolled_count -> 1, got {refreshed['enrolled_count']}"


# ---------------------------------------------------------------------------
# corner: schedule_assignment_unknown_section_not_found
# ---------------------------------------------------------------------------
def test_seat_unknown_section_not_found(api):
    """PRD §2.5: "All such identifiers are resolved left-to-right, path before body,
    before any business rule runs."
    PRD §2.5: "For example, posting a consequence under an incident that does not
    exist surfaces ERR_INCIDENT_NOT_FOUND before the body's consequence fields are
    examined."

    Design: Corner/errors/schedule_assignment_unknown_section_not_found
    """
    school = fx.create_school()
    student = fx.create_student(school["id"])
    enr = fx.create_enrollment(student["id"])
    resp = api.create_schedule_assignment(
        {"enrollment_id": enr["id"], "section_id": NON_EXISTENT_UUID}, REG)
    validate_error(resp, ApiErrorId.ERR_SECTION_NOT_FOUND.value, expected_status=404)


# --- local helper ---
def api_list_assignments(api, enrollment_id):
    from test_helpers import validate_paginated
    resp = api.list_schedule_assignments(REG, params={"enrollment_id": enrollment_id})
    return validate_paginated(resp)
