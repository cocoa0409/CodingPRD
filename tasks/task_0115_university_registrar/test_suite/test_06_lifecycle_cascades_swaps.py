"""Section lifecycle, cancellation cascade, swap requests, waitlist-promotion
chains, instructor double-booking, and immediate-consistency reads.

Translates Difficulty queue non_linear_state_machine (section revert, swap fork),
transitive_cascade (section-cancel chain, drop-promote-charge chain),
resource_temporal_overlap (instructor buffered geometry), plus Corner
cross-cutting and consistency-model instances.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    make_student_headers,
)
from test_helpers import fixtures as fx
from test_helpers import factories as F

REG = TEST_USERS["registrar_headers"]


# ==========================================================================
# Difficulty: non_linear_state_machine (section revert cycle)
# ==========================================================================
def test_section_open_close_reopen_cycle(api):
    """PRD §3.2: "Closing a section (`OPEN → CLOSED`) blocks new registrations but
    leaves existing `ENROLLED` and `WAITLISTED` entries untouched; reopening
    (`CLOSED → OPEN`) simply restores availability."

    Design: Difficulty/non_linear_state_machine/section_open_close_reopen_cycle
    """
    cat = fx.setup_catalog()
    sec = fx.make_section(cat["term"]["id"], cat["course"]["id"], cat["instructor"]["id"])
    fx.set_section_status(sec["id"], "CLOSED")
    reopened = fx.set_section_status(sec["id"], "OPEN")
    assert reopened["status"] == "OPEN"


def test_section_close_blocks_new_enrollment(api):
    """PRD §3.2: "Closing a section (`OPEN → CLOSED`) blocks new registrations".
    PRD §3.4: "The section's `status` must be `OPEN`, else `ERR_SECTION_NOT_OPEN`."

    A second, distinct probe of the OPEN->CLOSED transition: the closed state is
    observable through a rejected enrollment.

    Design: Difficulty/non_linear_state_machine/section_open_close_reopen_cycle
    """
    base = fx.setup_registration_open_section(seat_capacity=5)
    fx.set_section_status(base["section"]["id"], "CLOSED")
    stu, _ = fx.setup_student_ready(base["term"]["id"], base["program"]["id"])
    fx.set_clock(fx.CLOCK_REGISTRATION)
    v = fx.section_version(base["section"]["id"])
    resp = api.create_enrollment(
        F.create_enrollment_payload(base["term"]["id"], base["section"]["id"], v),
        make_student_headers(stu["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SECTION_NOT_OPEN.value, 409)


# ==========================================================================
# Difficulty: non_linear_state_machine (swap fork)
# ==========================================================================
def test_swap_commit_fork(api):
    """PRD §3.10: "If every add-leg precondition holds, the swap `COMMITS`: the
    system creates the added enrollment (born `REQUESTED`, then `ENROLLED`) on the
    add section, setting `added_enrollment_id`, incrementing the add section's
    `seats_taken`, and charging tuition; the successful add then drives the
    `drop_enrollment` to `DROPPED`".

    Design: Difficulty/non_linear_state_machine/swap_request_fork_commit_vs_abort
    """
    prog = fx.make_program()
    instr = fx.make_instructor()
    term = fx.make_term()
    c_old = fx.make_course(prog["id"])
    c_new = fx.make_course(prog["id"])
    s_old = fx.make_section(term["id"], c_old["id"], instr["id"],
                            meeting_days="MWF", meeting_start_min=540, meeting_end_min=590)
    s_new = fx.make_section(term["id"], c_new["id"], instr["id"],
                            meeting_days="TR", meeting_start_min=600, meeting_end_min=650)
    fx.advance_term(term["id"], "REGISTRATION_OPEN")
    stu, _ = fx.setup_student_ready(term["id"], prog["id"])
    fx.set_clock(fx.CLOCK_REGISTRATION)
    enr_old = fx.enroll(term["id"], s_old["id"], stu["id"])
    v_new = fx.section_version(s_new["id"])
    resp = api.create_swap_request(
        F.create_swap_request_payload(term["id"], enr_old["id"], s_new["id"], v_new),
        make_student_headers(stu["id"]),
    )
    swap = validate_success(resp, 201)
    assert swap["status"] == "COMMITTED"
    assert swap["added_enrollment_id"] is not None
    old_final = validate_success(api.get_enrollment(enr_old["id"], REG), 200)
    added = validate_success(api.get_enrollment(swap["added_enrollment_id"], REG), 200)
    assert old_final["registration_status"] == "DROPPED"
    assert added["registration_status"] == "ENROLLED"


def test_swap_abort_leaves_drop_enrollment_untouched(api):
    """PRD §3.10: "If any add-leg precondition fails, the swap `ABORTS`: the
    `drop_enrollment` is left untouched and still `ENROLLED`, no seat counts
    change, and the failing error is returned to the caller."
    PRD §3.10: "The `add_section_id` must be an `OPEN` section with `seats_taken`
    below `seat_capacity`, else `ERR_SECTION_FULL`."

    The add leg targets a full section (cap 1, already taken), so the swap aborts
    and the original enrollment stays ENROLLED.

    Design: Difficulty/non_linear_state_machine/swap_request_fork_commit_vs_abort
    """
    prog = fx.make_program()
    instr = fx.make_instructor()
    term = fx.make_term()
    c_old = fx.make_course(prog["id"])
    c_full = fx.make_course(prog["id"])
    s_old = fx.make_section(term["id"], c_old["id"], instr["id"],
                            meeting_days="MWF", meeting_start_min=540, meeting_end_min=590)
    s_full = fx.make_section(term["id"], c_full["id"], instr["id"], seat_capacity=1,
                             meeting_days="TR", meeting_start_min=600, meeting_end_min=650)
    fx.advance_term(term["id"], "REGISTRATION_OPEN")
    mover, _ = fx.setup_student_ready(term["id"], prog["id"])
    filler, _ = fx.setup_student_ready(term["id"], prog["id"],
                                       appointment_overrides={"priority_tier": 2})
    fx.set_clock(fx.CLOCK_REGISTRATION)
    enr_old = fx.enroll(term["id"], s_old["id"], mover["id"])
    fx.enroll(term["id"], s_full["id"], filler["id"])  # fills s_full (cap 1)
    v_full = fx.section_version(s_full["id"])
    resp = api.create_swap_request(
        F.create_swap_request_payload(term["id"], enr_old["id"], s_full["id"], v_full),
        make_student_headers(mover["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_SECTION_FULL.value, 409)
    old_final = validate_success(api.get_enrollment(enr_old["id"], REG), 200)
    assert old_final["registration_status"] == "ENROLLED", "aborted swap must leave drop enrollment ENROLLED"


# ==========================================================================
# Difficulty: transitive_cascade
# ==========================================================================
def test_section_cancel_drop_refund_owed_chain(api):
    """PRD §3.6: "Each `ENROLLED` enrollment is moved to `DROPPED` with the drop
    attributed to a section cancellation; that cascaded drop credits a full refund
    regardless of the clock ... and decrements the section's `seats_taken`. ...
    For every cascaded drop, the owning student's `tuition_owed_cents` and that
    student's `EnrollmentAppointment.enrolled_credit_hours` are recomputed."

    A depth-3 chain: cancel -> DROPPED -> FULL refund -> owed back to 0, even past
    every deadline.

    Design: Difficulty/transitive_cascade/section_cancel_drop_refund_owed_chain
    """
    base = fx.setup_one_enrolled_student(credit_hours=3)  # owed 150000
    fx.set_clock("2026-03-20T00:00:00Z")  # past every deadline
    fx.set_section_status(base["section"]["id"], "CANCELLED")
    enr = validate_success(api.get_enrollment(base["enrollment"]["id"], REG), 200)
    assert enr["registration_status"] == "DROPPED"
    assert enr["refund_cents"] == 150000  # FULL despite clock past deadlines
    stu = validate_success(api.get_student(base["student"]["id"], REG), 200)
    assert stu["tuition_owed_cents"] == 0
    sec = validate_success(api.get_section(base["section"]["id"], REG), 200)
    assert sec["seats_taken"] == 0


def test_section_cancel_drops_waitlisted_without_refund(api):
    """PRD §3.6: "Each `WAITLISTED` enrollment is likewise moved to `DROPPED`, but
    with no refund because no tuition was ever charged."

    A second probe of the cancel cascade on its other branch: the WAITLISTED
    enrollment is dropped and its refund_cents stays 0 (it was never charged),
    distinct from the ENROLLED full-refund branch.

    Design: Difficulty/transitive_cascade/section_cancel_drop_refund_owed_chain
    """
    base = fx.setup_enrolled_plus_waitlisted(credit_hours=3, waitlist_capacity=5)
    wl_enr_id = base["enrollment_b"]["id"]  # WAITLISTED, never charged
    fx.set_section_status(base["section"]["id"], "CANCELLED")
    enr_b = validate_success(api.get_enrollment(wl_enr_id, REG), 200)
    assert enr_b["registration_status"] == "DROPPED"
    assert enr_b["refund_cents"] == 0, "waitlisted cancel must credit no refund"
    data, _meta = validate_paginated(api.list_enrollment_refunds(wl_enr_id, REG))
    assert len(data) == 0, "no RefundTransaction for a never-charged waitlist drop"


def test_withdraw_promotes_waitlist_and_charges_chain(api):
    """PRD §3.5: "Both drop and withdraw trigger this promotion."
    PRD §3.5: "This system promotion increments the section's `seats_taken` by one
    ... sets the promoted enrollment's `tuition_charged_cents` to the course's
    `credit_hours` times the term's `per_credit_cost_cents`; recomputes that
    promoted student's `tuition_owed_cents`".

    A second probe of the promote-and-charge chain driven by a WITHDRAW (a
    different releasing transition than the drop): the withdraw releases the seat,
    the WAITLISTED head is promoted to ENROLLED, and that promoted student is
    charged 150000.

    Design: Difficulty/transitive_cascade/drop_releases_seat_promotes_waitlist_charges_chain
    """
    base = fx.setup_enrolled_plus_waitlisted(credit_hours=3, waitlist_capacity=5)
    fx.set_clock("2026-02-20T00:00:00Z")  # withdraw window (after drop_deadline)
    fx.withdraw(base["enrollment_a"]["id"], base["student_a"]["id"])
    enr_b = validate_success(api.get_enrollment(base["enrollment_b"]["id"], REG), 200)
    assert enr_b["registration_status"] == "ENROLLED"
    b_after = validate_success(api.get_student(base["student_b"]["id"], REG), 200)
    assert b_after["tuition_owed_cents"] == 150000, "promotion via withdraw must charge the promoted student"


def test_drop_promotes_waitlist_and_charges_chain(api):
    """PRD §3.5: "the head of that section's waitlist is promoted ... This system
    promotion increments the section's `seats_taken` by one ... sets the promoted
    enrollment's `tuition_charged_cents` to the course's `credit_hours` times the
    term's `per_credit_cost_cents`; recomputes that promoted student's
    `tuition_owed_cents`".

    A depth-3 chain from a Student DROP: release -> promote WAITLISTED head ->
    charge promoted student's tuition (owed 0 -> 150000).

    Design: Difficulty/transitive_cascade/drop_releases_seat_promotes_waitlist_charges_chain
    """
    base = fx.setup_enrolled_plus_waitlisted(credit_hours=3, waitlist_capacity=5)
    # Student B is WAITLISTED, never charged yet.
    b_before = validate_success(api.get_student(base["student_b"]["id"], REG), 200)
    assert b_before["tuition_owed_cents"] == 0
    fx.drop(base["enrollment_a"]["id"], base["student_a"]["id"])
    enr_a = validate_success(api.get_enrollment(base["enrollment_a"]["id"], REG), 200)
    enr_b = validate_success(api.get_enrollment(base["enrollment_b"]["id"], REG), 200)
    assert enr_a["registration_status"] == "DROPPED"
    assert enr_b["registration_status"] == "ENROLLED"
    b_after = validate_success(api.get_student(base["student_b"]["id"], REG), 200)
    assert b_after["tuition_owed_cents"] == 150000, "promotion must charge the promoted student"
    sec = validate_success(api.get_section(base["section"]["id"], REG), 200)
    assert sec["seats_taken"] == 1


# ==========================================================================
# Difficulty: resource_temporal_overlap (instructor buffered geometry)
# ==========================================================================
def test_instructor_double_booking_within_buffer_rejected(api):
    """PRD §3.2: "using the instructor's `gap_minutes`, the new section conflicts
    with an existing one when the new section's start is earlier than the existing
    section's end plus the buffer, and the existing section's start is earlier than
    the new section's end plus the buffer — so even two windows that do not overlap
    but sit closer than the buffer are in conflict. A violation is rejected with
    `ERR_INSTRUCTOR_DOUBLE_BOOKED`."

    gap_minutes=15: a [600,650) section only 10 min after [540,590) on shared MWF
    is rejected even though the windows do not overlap.

    Design: Difficulty/resource_temporal_overlap/instructor_double_booking_buffered
    """
    prog = fx.make_program()
    instr = fx.make_instructor(gap_minutes=15)
    term = fx.make_term()
    ca = fx.make_course(prog["id"])
    cb = fx.make_course(prog["id"])
    fx.make_section(term["id"], ca["id"], instr["id"],
                    meeting_days="MWF", meeting_start_min=540, meeting_end_min=590)
    resp = api.create_section(
        F.create_section_payload(term["id"], cb["id"], instr["id"],
                                 meeting_days="MWF", meeting_start_min=600, meeting_end_min=650),
        REG,
    )
    validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_DOUBLE_BOOKED.value, 409)


def test_instructor_sections_outside_buffer_allowed(api):
    """PRD §3.2: "Two sections conflict when they share at least one day letter in
    their `meeting_days` and their meeting windows are not separated by the
    instructor's required buffer."

    gap_minutes=15: a [610,660) section 20 min after [540,590) clears the buffer
    and is accepted (the negative side of the buffered rule).

    Design: Difficulty/resource_temporal_overlap/instructor_double_booking_buffered
    """
    prog = fx.make_program()
    instr = fx.make_instructor(gap_minutes=15)
    term = fx.make_term()
    ca = fx.make_course(prog["id"])
    cb = fx.make_course(prog["id"])
    fx.make_section(term["id"], ca["id"], instr["id"],
                    meeting_days="MWF", meeting_start_min=540, meeting_end_min=590)
    resp = api.create_section(
        F.create_section_payload(term["id"], cb["id"], instr["id"],
                                 meeting_days="MWF", meeting_start_min=610, meeting_end_min=660),
        REG,
    )
    data = validate_success(resp, 201)
    assert data["status"] == "OPEN"


# ==========================================================================
# Corner: consistency_model
# ==========================================================================
def test_enrolled_credit_hours_visible_immediately(api):
    """PRD §3.3: "The appointment's computed `enrolled_credit_hours` starts at 0
    and tracks the sum of `credit_hours` over the student's `ENROLLED` and
    `WAITLISTED` enrollments in that term".
    PRD §3.4: "the appointment's `enrolled_credit_hours` are recomputed."

    After enrolling in a 3cr section, the appointment reports 3 on the next read.

    Design: Corner/consistency_model/enrolled_credit_hours_visible_immediately
    """
    base = fx.setup_registration_open_section(seat_capacity=5,
                                              course_overrides={"credit_hours": 3})
    stu, appt = fx.setup_student_ready(base["term"]["id"], base["program"]["id"])
    fx.set_clock(fx.CLOCK_REGISTRATION)
    fx.enroll(base["term"]["id"], base["section"]["id"], stu["id"])
    appt_final = validate_success(api.get_appointment(appt["id"], REG), 200)
    assert appt_final["enrolled_credit_hours"] == 3
