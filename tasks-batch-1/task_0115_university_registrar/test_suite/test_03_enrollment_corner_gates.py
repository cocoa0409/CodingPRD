"""Corner-queue enrollment lifecycle preconditions: initial state, duplicates,
windows, grading guards, waitlist capacity, prerequisites/corequisites, credit
limit, appointment window, and the standalone add-window violation.
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


def _enroll_resp(api, term_id, section_id, student_id, version=None):
    if version is None:
        version = fx.section_version(section_id)
    return api.create_enrollment(
        F.create_enrollment_payload(term_id, section_id, version),
        make_student_headers(student_id),
    )


def test_new_enrollment_with_free_seat_is_enrolled_ungraded(api):
    """PRD §3.4: "A new enrollment is born in `REQUESTED` and is immediately
    evaluated; depending on seat availability it resolves to `ENROLLED` or
    `WAITLISTED`, both within the same request."
    PRD §3.4: "`tuition_charged_cents` is set to the course's `credit_hours` times
    the term's `per_credit_cost_cents`".

    Design: Corner/state_machines/enrollment_initial_state_is_requested_then_enrolled
    """
    base = fx.setup_one_enrolled_student(credit_hours=3)
    enr = base["enrollment"]
    assert enr["registration_status"] == "ENROLLED"
    assert enr["grade_status"] == "UNGRADED"
    assert enr["tuition_charged_cents"] == 150000


def test_duplicate_enrollment_same_section_rejected(api):
    """PRD §3.4: "The student must not already hold a non-terminal enrollment in
    the same section, else `ERR_DUPLICATE_ENROLLMENT`."

    Design: Corner/state_machines/duplicate_enrollment_same_section_rejected
    """
    base = fx.setup_one_enrolled_student(credit_hours=3, seat_capacity=5)
    resp = _enroll_resp(api, base["term"]["id"], base["section"]["id"], base["student"]["id"])
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ENROLLMENT.value, 409)


def test_drop_after_drop_deadline_window_closed(api):
    """PRD §3.5: "a drop attempted after the drop deadline is rejected with
    `ERR_DROP_WINDOW_CLOSED`."

    Design: Corner/state_machines/drop_after_drop_deadline_window_closed
    """
    base = fx.setup_one_enrolled_student(credit_hours=3)
    fx.set_clock("2026-02-20T00:00:00Z")  # past drop_deadline (2026-02-15)
    resp = api.drop_enrollment(base["enrollment"]["id"], make_student_headers(base["student"]["id"]))
    validate_error(resp, ApiErrorId.ERR_DROP_WINDOW_CLOSED.value, 409)


def test_withdraw_before_drop_deadline_window_closed(api):
    """PRD §3.5: "A **withdraw** applies after the full-refund window. It is
    permitted when the current instant is after the term's `drop_deadline` and at
    or before its `withdraw_deadline` ... outside that window the request is
    rejected with `ERR_WITHDRAW_WINDOW_CLOSED`."

    Design: Corner/state_machines/withdraw_before_drop_deadline_window_closed
    """
    base = fx.setup_one_enrolled_student(credit_hours=3)
    # Clock still in the drop window (2026-01-10), before drop_deadline.
    resp = api.withdraw_enrollment(base["enrollment"]["id"], make_student_headers(base["student"]["id"]))
    validate_error(resp, ApiErrorId.ERR_WITHDRAW_WINDOW_CLOSED.value, 409)


def test_grade_already_graded_rejected(api):
    """PRD §3.8: "The enrollment's `registration_status` must be `ENROLLED` and its
    `grade_status` must still be `UNGRADED`, or the request is rejected with
    `ERR_ALREADY_GRADED`."

    Design: Corner/state_machines/grade_already_graded_rejected
    """
    base = fx.setup_one_enrolled_student(credit_hours=3)
    fx.advance_term(base["term"]["id"], "IN_SESSION")
    fx.grade(base["enrollment"]["id"], "B")
    resp = api.grade_enrollment(base["enrollment"]["id"], {"letter_grade": "A"}, ADV)
    validate_error(resp, ApiErrorId.ERR_ALREADY_GRADED.value, 409)


def test_waitlist_full_rejected(api):
    """PRD §3.4: "the enrollment is routed to the waitlist — but only if the
    section's `waitlist_count` is below its `waitlist_capacity`, else the request
    is rejected with `ERR_WAITLIST_FULL`."

    Design: Corner/state_machines/waitlist_full_rejected
    """
    base = fx.setup_registration_open_section(seat_capacity=1, waitlist_capacity=1,
                                              course_overrides={"credit_hours": 3})
    a, _ = fx.setup_student_ready(base["term"]["id"], base["program"]["id"])
    b, _ = fx.setup_student_ready(base["term"]["id"], base["program"]["id"],
                                  appointment_overrides={"priority_tier": 2})
    c, _ = fx.setup_student_ready(base["term"]["id"], base["program"]["id"],
                                  appointment_overrides={"priority_tier": 3})
    fx.set_clock(fx.CLOCK_REGISTRATION)
    fx.enroll(base["term"]["id"], base["section"]["id"], a["id"])  # ENROLLED
    fx.enroll(base["term"]["id"], base["section"]["id"], b["id"])  # WAITLISTED (waitlist full)
    resp = _enroll_resp(api, base["term"]["id"], base["section"]["id"], c["id"])
    validate_error(resp, ApiErrorId.ERR_WAITLIST_FULL.value, 409)


def test_corequisite_unmet_rejected(api):
    """PRD §3.4: "Every `COREQUISITE` requirement must be satisfied by a same-term
    enrollment in the required course whose `registration_status` is `ENROLLED`,
    `WAITLISTED`, or `REQUESTED`, else `ERR_COREQUISITE_NOT_MET`."

    Design: Corner/state_machines/coreq_unmet_rejected
    """
    prog = fx.make_program()
    instr = fx.make_instructor()
    term = fx.make_term()
    cs201 = fx.make_course(prog["id"], code="CS201", credit_hours=4)
    cs301 = fx.make_course(prog["id"], code="CS301", credit_hours=3)
    fx.make_requirement(cs301["id"], cs201["id"], "COREQUISITE")
    sec = fx.make_section(term["id"], cs301["id"], instr["id"])
    fx.advance_term(term["id"], "REGISTRATION_OPEN")
    stu, _ = fx.setup_student_ready(term["id"], prog["id"])
    fx.set_clock(fx.CLOCK_REGISTRATION)
    resp = _enroll_resp(api, term["id"], sec["id"], stu["id"])
    validate_error(resp, ApiErrorId.ERR_COREQUISITE_NOT_MET.value, 422)


def test_credit_limit_exceeded_rejected(api):
    """PRD §3.4: "Adding the section's `credit_hours` to the appointment's current
    `enrolled_credit_hours` must not exceed the appointment's `max_credit_hours`,
    else `ERR_CREDIT_LIMIT_EXCEEDED`."

    Design: Corner/state_machines/credit_limit_exceeded_rejected
    """
    prog = fx.make_program()
    instr = fx.make_instructor()
    term = fx.make_term()
    c1 = fx.make_course(prog["id"], credit_hours=3)
    c2 = fx.make_course(prog["id"], credit_hours=3)
    s1 = fx.make_section(term["id"], c1["id"], instr["id"],
                         meeting_days="MWF", meeting_start_min=540, meeting_end_min=590)
    s2 = fx.make_section(term["id"], c2["id"], instr["id"],
                         meeting_days="TR", meeting_start_min=600, meeting_end_min=650)
    fx.advance_term(term["id"], "REGISTRATION_OPEN")
    stu, _ = fx.setup_student_ready(term["id"], prog["id"], max_credit_hours=3)
    fx.set_clock(fx.CLOCK_REGISTRATION)
    fx.enroll(term["id"], s1["id"], stu["id"])  # 3 credits, cap reached
    resp = _enroll_resp(api, term["id"], s2["id"], stu["id"])  # +3 would exceed cap 3
    validate_error(resp, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED.value, 409)


def test_enroll_before_appointment_window_open(api):
    """PRD §3.4: "An `EnrollmentAppointment` must exist for the student and term
    and the current instant must be at or after its `window_opens_at`, else
    `ERR_APPOINTMENT_NOT_OPEN`."

    Design: Corner/state_machines/enroll_before_appointment_window_open
    """
    base = fx.setup_registration_open_section(seat_capacity=5)
    stu, _ = fx.setup_student_ready(base["term"]["id"], base["program"]["id"],
                                    window_opens_at="2026-01-05T00:00:00Z")
    fx.set_clock("2026-01-02T00:00:00Z")  # before window_opens_at
    resp = _enroll_resp(api, base["term"]["id"], base["section"]["id"], stu["id"])
    validate_error(resp, ApiErrorId.ERR_APPOINTMENT_NOT_OPEN.value, 409)


def test_invalid_grade_letter_rejected(api):
    """PRD §3.8: "The submitted `letter_grade` must be one of `A`, `B`, `C`, `D`,
    or `F` — the `W` mark is produced only by a withdrawal, never by grade entry —
    and any other value is rejected with `ERR_INVALID_GRADE`."

    Design: Corner/state_machines/invalid_grade_letter_rejected
    """
    base = fx.setup_one_enrolled_student(credit_hours=3)
    fx.advance_term(base["term"]["id"], "IN_SESSION")
    resp = api.grade_enrollment(base["enrollment"]["id"], {"letter_grade": "W"}, ADV)
    validate_error(resp, ApiErrorId.ERR_INVALID_GRADE.value, 422)


def test_prerequisite_satisfied_enroll_succeeds(api):
    """PRD §3.4: "a prerequisite counts as satisfied when the student holds a
    graded, non-`W` enrollment in the required course from a prior or closed term
    whose grade points meet or exceed the requirement's `min_grade_points`."

    Design: Corner/state_machines/prerequisite_satisfied_enroll_succeeds
    """
    prog = fx.make_program()
    instr = fx.make_instructor()
    cs101 = fx.make_course(prog["id"], code="CS101", credit_hours=3)
    cs201 = fx.make_course(prog["id"], code="CS201", credit_hours=4)
    fx.make_requirement(cs201["id"], cs101["id"], "PREREQUISITE", min_grade_points=2.0)
    # Prior term: same student earns B (3.0 >= 2.0) in CS101, term then CLOSED.
    stu, _prior_enr, _prior_term = fx.setup_prior_graded_course(prog, instr, cs101, letter_grade="B")
    # New open term with a CS201 section; reuse the same student.
    t1 = fx.make_term(name="T1")
    s1 = fx.make_section(t1["id"], cs201["id"], instr["id"],
                         meeting_days="TR", meeting_start_min=600, meeting_end_min=650)
    fx.advance_term(t1["id"], "REGISTRATION_OPEN")
    fx.make_appointment(t1["id"], stu["id"], max_credit_hours=12)
    fx.set_clock(fx.CLOCK_REGISTRATION)
    resp = _enroll_resp(api, t1["id"], s1["id"], stu["id"])
    data = validate_success(resp, 201)
    assert data["registration_status"] == "ENROLLED"


def test_add_window_closed_after_deadline(api):
    """PRD §3.4: "The term must be `REGISTRATION_OPEN` and the current instant at
    or before the term's `add_deadline`, else `ERR_ADD_WINDOW_CLOSED`."

    Design: Corner/validations/error_add_window_closed_after_deadline
    """
    base = fx.setup_registration_open_section(seat_capacity=5)
    stu, _ = fx.setup_student_ready(base["term"]["id"], base["program"]["id"])
    fx.set_clock("2026-02-10T00:00:00Z")  # past add_deadline, no holds
    resp = _enroll_resp(api, base["term"]["id"], base["section"]["id"], stu["id"])
    validate_error(resp, ApiErrorId.ERR_ADD_WINDOW_CLOSED.value, 409)
