"""Enrollment registration gates: holds, windows, section state, duplicates,
prerequisites/corequisites, time conflicts, credit limits, OCC, and seat routing.

Translates Difficulty queue instances (cross_entity_state_dependency,
priority_pair_validation_conflict, boundary_precision_check seat boundary,
resource_temporal_overlap student leg, cross-cutting OCC) and the matching
Corner state_machines precondition instances.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_student_headers,
)
from test_helpers import fixtures as fx
from test_helpers import factories as F

REG = TEST_USERS["registrar_headers"]
ADV = TEST_USERS["advisor_headers"]
BUR = TEST_USERS["bursar_headers"]


def _enroll_resp(api, term_id, section_id, student_id, version=None):
    """Issue an enroll request and return the raw response (for error assertions)."""
    if version is None:
        version = fx.section_version(section_id)
    payload = F.create_enrollment_payload(term_id, section_id, version)
    return api.create_enrollment(payload, make_student_headers(student_id))


# ==========================================================================
# Difficulty: cross_entity_state_dependency
# ==========================================================================
def test_enroll_blocked_by_active_advising_hold(api):
    """PRD §3.4: "The student must have zero `ACTIVE` holds, or the request is
    rejected with `ERR_REGISTRATION_HOLD`."

    Design: Difficulty/cross_entity_state_dependency/enroll_blocked_by_active_hold
    """
    base = fx.setup_registration_open_section(seat_capacity=5)
    stu, _appt = fx.setup_student_ready(base["term"]["id"], base["program"]["id"])
    fx.make_hold(stu["id"], "ADVISING")
    fx.set_clock(fx.CLOCK_REGISTRATION)
    resp = _enroll_resp(api, base["term"]["id"], base["section"]["id"], stu["id"])
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_HOLD.value, 403)


def test_enroll_blocked_by_financial_hold(api):
    """PRD §3.4: "The student must have zero `ACTIVE` holds, or the request is
    rejected with `ERR_REGISTRATION_HOLD`."

    Design: Difficulty/cross_entity_state_dependency/enroll_blocked_by_active_hold
    """
    base = fx.setup_registration_open_section(seat_capacity=5)
    stu, _appt = fx.setup_student_ready(base["term"]["id"], base["program"]["id"])
    fx.make_hold(stu["id"], "FINANCIAL")
    fx.set_clock(fx.CLOCK_REGISTRATION)
    resp = _enroll_resp(api, base["term"]["id"], base["section"]["id"], stu["id"])
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_HOLD.value, 403)


def test_enroll_blocked_by_closed_section(api):
    """PRD §3.4: "The section's `status` must be `OPEN`, else `ERR_SECTION_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/enroll_blocked_by_section_not_open
    """
    base = fx.setup_registration_open_section(seat_capacity=5)
    fx.set_section_status(base["section"]["id"], "CLOSED")
    stu, _appt = fx.setup_student_ready(base["term"]["id"], base["program"]["id"])
    fx.set_clock(fx.CLOCK_REGISTRATION)
    resp = _enroll_resp(api, base["term"]["id"], base["section"]["id"], stu["id"])
    validate_error(resp, ApiErrorId.ERR_SECTION_NOT_OPEN.value, 409)


def test_enroll_blocked_by_cancelled_section(api):
    """PRD §3.4: "The section's `status` must be `OPEN`, else `ERR_SECTION_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/enroll_blocked_by_section_not_open
    """
    base = fx.setup_registration_open_section(seat_capacity=5)
    fx.set_section_status(base["section"]["id"], "CANCELLED")
    stu, _appt = fx.setup_student_ready(base["term"]["id"], base["program"]["id"])
    fx.set_clock(fx.CLOCK_REGISTRATION)
    resp = _enroll_resp(api, base["term"]["id"], base["section"]["id"], stu["id"])
    validate_error(resp, ApiErrorId.ERR_SECTION_NOT_OPEN.value, 409)


# ==========================================================================
# Difficulty: priority_pair_validation_conflict
# ==========================================================================
def test_hold_beats_add_window_closed(api):
    """PRD §3.11: "the hold check (`ERR_REGISTRATION_HOLD`), then the add-window
    check (`ERR_ADD_WINDOW_CLOSED`)".

    A held student enrolling after add_deadline must receive ERR_REGISTRATION_HOLD,
    the earlier check, not ERR_ADD_WINDOW_CLOSED.

    Design: Difficulty/priority_pair_validation_conflict/hold_beats_add_window_closed
    """
    base = fx.setup_registration_open_section(seat_capacity=5)
    stu, _appt = fx.setup_student_ready(base["term"]["id"], base["program"]["id"])
    fx.make_hold(stu["id"], "FINANCIAL")
    fx.set_clock("2026-02-10T00:00:00Z")  # past add_deadline (2026-02-01)
    resp = _enroll_resp(api, base["term"]["id"], base["section"]["id"], stu["id"])
    validate_error(resp, ApiErrorId.ERR_REGISTRATION_HOLD.value, 403)


def test_add_window_surfaces_once_hold_cleared(api):
    """PRD §3.11: "the hold check (`ERR_REGISTRATION_HOLD`), then the add-window
    check (`ERR_ADD_WINDOW_CLOSED`)".

    A second probe of the same precedence pair: with the clock past add_deadline,
    the held student gets ERR_REGISTRATION_HOLD; after the hold is cleared, the
    very same request now surfaces the later ERR_ADD_WINDOW_CLOSED — proving the
    hold genuinely pre-empted the add-window check rather than the window simply
    being open.

    Design: Difficulty/priority_pair_validation_conflict/hold_beats_add_window_closed
    """
    base = fx.setup_registration_open_section(seat_capacity=5)
    stu, _appt = fx.setup_student_ready(base["term"]["id"], base["program"]["id"])
    hold = fx.make_hold(stu["id"], "FINANCIAL")
    fx.set_clock("2026-02-10T00:00:00Z")  # past add_deadline
    resp_held = _enroll_resp(api, base["term"]["id"], base["section"]["id"], stu["id"])
    validate_error(resp_held, ApiErrorId.ERR_REGISTRATION_HOLD.value, 403)
    # Clear the hold (Bursar clears a FINANCIAL hold) and retry the same request.
    validate_success(api.clear_hold(hold["id"], BUR), 200)
    resp_cleared = _enroll_resp(api, base["term"]["id"], base["section"]["id"], stu["id"])
    validate_error(resp_cleared, ApiErrorId.ERR_ADD_WINDOW_CLOSED.value, 409)


def test_prerequisite_beats_credit_limit(api):
    """PRD §3.11: "then prerequisites (`ERR_PREREQUISITE_NOT_MET`), then
    corequisites (`ERR_COREQUISITE_NOT_MET`), then the time-conflict check
    (`ERR_TIME_CONFLICT`), then the credit-limit check (`ERR_CREDIT_LIMIT_EXCEEDED`)".

    A 4cr course with an unmet prerequisite and an appointment cap of 3 must fail
    on the earlier prerequisite check, not the later credit-limit check.

    Design: Difficulty/priority_pair_validation_conflict/prerequisite_beats_credit_limit
    """
    prog = fx.make_program()
    instr = fx.make_instructor()
    term = fx.make_term()
    cs101 = fx.make_course(prog["id"], code="CS101", credit_hours=3)
    cs201 = fx.make_course(prog["id"], code="CS201", credit_hours=4)
    fx.make_requirement(cs201["id"], cs101["id"], "PREREQUISITE", min_grade_points=2.0)
    sec = fx.make_section(term["id"], cs201["id"], instr["id"])
    fx.advance_term(term["id"], "REGISTRATION_OPEN")
    stu, _appt = fx.setup_student_ready(term["id"], prog["id"], max_credit_hours=3)
    fx.set_clock(fx.CLOCK_REGISTRATION)
    resp = _enroll_resp(api, term["id"], sec["id"], stu["id"])
    validate_error(resp, ApiErrorId.ERR_PREREQUISITE_NOT_MET.value, 422)


def test_credit_limit_surfaces_once_prerequisite_satisfied(api):
    """PRD §3.11: "then prerequisites (`ERR_PREREQUISITE_NOT_MET`) ... then the
    credit-limit check (`ERR_CREDIT_LIMIT_EXCEEDED`)".

    A second probe of the same precedence pair: a 4cr CS201 with an unmet prereq
    and a cap-3 appointment fails on the prerequisite; once the student satisfies
    the prerequisite (a prior-term B in CS101), the same 4cr add into a cap-3
    appointment now fails on the later credit-limit check — proving the prereq
    check pre-empted the credit-limit check.

    Design: Difficulty/priority_pair_validation_conflict/prerequisite_beats_credit_limit
    """
    prog = fx.make_program()
    instr = fx.make_instructor()
    cs101 = fx.make_course(prog["id"], code="CS101", credit_hours=3)
    cs201 = fx.make_course(prog["id"], code="CS201", credit_hours=4)
    fx.make_requirement(cs201["id"], cs101["id"], "PREREQUISITE", min_grade_points=2.0)
    # Prior closed term: the student earns B in CS101, satisfying the prerequisite.
    stu, _prior, _t0 = fx.setup_prior_graded_course(prog, instr, cs101, letter_grade="B")
    # New open term: a CS201 section, appointment cap 3 (a 4cr add exceeds it).
    t1 = fx.make_term(name="T1")
    sec = fx.make_section(t1["id"], cs201["id"], instr["id"],
                          meeting_days="TR", meeting_start_min=600, meeting_end_min=650)
    fx.advance_term(t1["id"], "REGISTRATION_OPEN")
    fx.make_appointment(t1["id"], stu["id"], max_credit_hours=3)
    fx.set_clock(fx.CLOCK_REGISTRATION)
    resp = _enroll_resp(api, t1["id"], sec["id"], stu["id"])
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value, 409)


# ==========================================================================
# Difficulty: boundary_precision_check (seat capacity boundary)
# ==========================================================================
def test_seat_capacity_boundary_enrolled_then_waitlisted(api):
    """PRD §3.4: "If the section's `seats_taken` is below its `seat_capacity`, the
    enrollment becomes `ENROLLED`".
    PRD §3.4: "If instead the section is full (`seats_taken` equals
    `seat_capacity`), the enrollment is routed to the waitlist".
    PRD §3.4: "the enrollment's `waitlist_position` is assigned as the new
    `waitlist_count` after the increment".

    Design: Difficulty/boundary_precision_check/seat_capacity_boundary_enrolled_vs_waitlisted
    """
    base = fx.setup_registration_open_section(seat_capacity=1, waitlist_capacity=5,
                                              course_overrides={"credit_hours": 3})
    a, _ = fx.setup_student_ready(base["term"]["id"], base["program"]["id"])
    b, _ = fx.setup_student_ready(base["term"]["id"], base["program"]["id"],
                                  appointment_overrides={"priority_tier": 2})
    fx.set_clock(fx.CLOCK_REGISTRATION)
    enr_a = fx.enroll(base["term"]["id"], base["section"]["id"], a["id"])  # seats_taken 0<1
    enr_b = fx.enroll(base["term"]["id"], base["section"]["id"], b["id"])  # seats_taken 1==1
    assert enr_a["registration_status"] == "ENROLLED"
    assert enr_b["registration_status"] == "WAITLISTED"
    assert enr_b["waitlist_position"] == 1


def test_seat_routing_enrolled_charges_tuition(api):
    """PRD §3.4: "If the section's `seats_taken` is below its `seat_capacity`, the
    enrollment becomes `ENROLLED`: the section's `seats_taken` increments by one
    and its `version` increments by one; `tuition_charged_cents` is set to the
    course's `credit_hours` times the term's `per_credit_cost_cents`".

    Design: Difficulty/boundary_precision_check/seat_capacity_boundary_enrolled_vs_waitlisted
    """
    base = fx.setup_one_enrolled_student(credit_hours=3, seat_capacity=2)
    enr = base["enrollment"]
    assert enr["registration_status"] == "ENROLLED"
    assert enr["tuition_charged_cents"] == 150000  # 3 * 50000
    sec = validate_success(api.get_section(base["section"]["id"], REG), 200)
    assert sec["seats_taken"] == 1


# ==========================================================================
# Difficulty: resource_temporal_overlap (student schedule leg)
# ==========================================================================
def test_student_time_conflict_rejected(api):
    """PRD §3.4: "The section's meeting window must not overlap any of the
    student's other `ENROLLED` sections on a shared day, else `ERR_TIME_CONFLICT`;
    this student-schedule check uses half-open overlap with adjacency allowed —
    one section ending exactly when another begins is not a conflict, and no
    buffer applies."

    Design: Difficulty/resource_temporal_overlap/student_meeting_overlap_adjacency_allowed
    """
    prog = fx.make_program()
    # Distinct instructors so the instructor double-booking rule never fires;
    # the rule under test is the student-schedule overlap, not instructor conflict.
    instr_x = fx.make_instructor()
    instr_y = fx.make_instructor()
    term = fx.make_term()
    cx = fx.make_course(prog["id"])
    cy = fx.make_course(prog["id"])
    sx = fx.make_section(term["id"], cx["id"], instr_x["id"],
                         meeting_days="MWF", meeting_start_min=540, meeting_end_min=590)
    sy = fx.make_section(term["id"], cy["id"], instr_y["id"],
                         meeting_days="MWF", meeting_start_min=570, meeting_end_min=620)
    fx.advance_term(term["id"], "REGISTRATION_OPEN")
    stu, _ = fx.setup_student_ready(term["id"], prog["id"])
    fx.set_clock(fx.CLOCK_REGISTRATION)
    fx.enroll(term["id"], sx["id"], stu["id"])  # [540,590) MWF
    resp = _enroll_resp(api, term["id"], sy["id"], stu["id"])  # [570,620) overlaps
    validate_error(resp, ApiErrorId.ERR_TIME_CONFLICT.value, 409)


def test_student_adjacent_sections_allowed(api):
    """PRD §3.4: "this student-schedule check uses half-open overlap with adjacency
    allowed — one section ending exactly when another begins is not a conflict,
    and no buffer applies."

    Design: Difficulty/resource_temporal_overlap/student_meeting_overlap_adjacency_allowed
    """
    prog = fx.make_program()
    # Distinct instructors so the only rule in play is the student-schedule check.
    instr_x = fx.make_instructor()
    instr_y = fx.make_instructor()
    term = fx.make_term()
    cx = fx.make_course(prog["id"])
    cy = fx.make_course(prog["id"])
    sx = fx.make_section(term["id"], cx["id"], instr_x["id"],
                         meeting_days="MWF", meeting_start_min=540, meeting_end_min=590)
    sy = fx.make_section(term["id"], cy["id"], instr_y["id"],
                         meeting_days="MWF", meeting_start_min=590, meeting_end_min=640)
    fx.advance_term(term["id"], "REGISTRATION_OPEN")
    stu, _ = fx.setup_student_ready(term["id"], prog["id"])
    fx.set_clock(fx.CLOCK_REGISTRATION)
    fx.enroll(term["id"], sx["id"], stu["id"])  # [540,590) MWF
    resp = _enroll_resp(api, term["id"], sy["id"], stu["id"])  # [590,640) adjacent
    data = validate_success(resp, 201)
    assert data["registration_status"] == "ENROLLED"


# ==========================================================================
# Cross-cutting: optimistic concurrency
# ==========================================================================
def test_stale_section_version_rejected(api):
    """PRD §2.5: "If they differ — meaning another writer has advanced the
    section's `version` since the client last read it, for example by taking what
    the client believed was an available seat — the request is rejected with
    `ERR_STALE_VERSION` and HTTP status 412."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_section_version_rejected
    """
    base = fx.setup_registration_open_section(seat_capacity=5)
    a, _ = fx.setup_student_ready(base["term"]["id"], base["program"]["id"])
    b, _ = fx.setup_student_ready(base["term"]["id"], base["program"]["id"],
                                  appointment_overrides={"priority_tier": 2})
    fx.set_clock(fx.CLOCK_REGISTRATION)
    stale_v = fx.section_version(base["section"]["id"])  # version observed before any enroll
    # Student A takes a seat, advancing the section version past stale_v.
    validate_success(
        api.create_enrollment(
            F.create_enrollment_payload(base["term"]["id"], base["section"]["id"], stale_v),
            make_student_headers(a["id"]),
        ),
        201,
    )
    # Student B re-uses the now-stale version.
    resp = api.create_enrollment(
        F.create_enrollment_payload(base["term"]["id"], base["section"]["id"], stale_v),
        make_student_headers(b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, 412)


def test_section_version_increments_on_enroll(api):
    """PRD §2.4: "When a transition recomputes a derived field on a resource — for
    instance updating a `Section`'s `seats_taken` ... its `version` increments.
    This is why a single enrollment can advance a section's `version` even though
    the client only created an enrollment."

    Design: Corner/cross_cutting_complexity_layers/section_version_increments_on_enroll
    """
    base = fx.setup_registration_open_section(seat_capacity=5)
    create_version = base["section"]["version"]
    stu, _ = fx.setup_student_ready(base["term"]["id"], base["program"]["id"])
    fx.set_clock(fx.CLOCK_REGISTRATION)
    fx.enroll(base["term"]["id"], base["section"]["id"], stu["id"])
    sec = validate_success(api.get_section(base["section"]["id"], REG), 200)
    assert sec["version"] == create_version + 1, (
        f"version must advance by 1 on enroll, {create_version} -> {sec['version']}"
    )
    assert sec["seats_taken"] == 1
