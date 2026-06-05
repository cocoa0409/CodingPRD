"""Composite setup helpers for the University Registrar API.

Every test runs against a fresh, empty database (the harness restarts the server
before each test). These helpers build the multi-step preambles that most claims
require — catalog, term lifecycle, students, appointments, the logical clock, and
enrollments through to late lifecycle stages — so tests can focus on assertions.

All setup calls use get_success_data() (lenient 2xx validator) so a broken
precondition surfaces as a clear "Setup step failed" message.

Identity threading: a Student is entity_backed, so every ownership-gated call
(enroll/drop/withdraw/swap) uses make_student_headers(student_id) with the real
Student.id — never the shared TEST_USERS["student_headers"] constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_student_headers
from . import factories as F
from .constants import (
    CLOCK_REGISTRATION,
    WINDOW_OPENS_AT,
)

REG = TEST_USERS["registrar_headers"]
ADV = TEST_USERS["advisor_headers"]
BUR = TEST_USERS["bursar_headers"]


# ==========================================================================
# Low-level single-entity creators (return the data dict).
# ==========================================================================
def make_program(**overrides) -> dict:
    return get_success_data(api_client.create_program(F.create_program_payload(**overrides), REG))


def make_instructor(**overrides) -> dict:
    return get_success_data(api_client.create_instructor(F.create_instructor_payload(**overrides), REG))


def make_term(**overrides) -> dict:
    return get_success_data(api_client.create_term(F.create_term_payload(**overrides), REG))


def make_course(program_id, **overrides) -> dict:
    return get_success_data(api_client.create_course(F.create_course_payload(program_id, **overrides), REG))


def make_section(term_id, course_id, instructor_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_section(
            F.create_section_payload(term_id, course_id, instructor_id, **overrides), REG
        )
    )


def make_student(program_id, **overrides) -> dict:
    return get_success_data(api_client.create_student(F.create_student_payload(program_id, **overrides), REG))


def make_appointment(term_id, student_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_appointment(F.create_appointment_payload(term_id, student_id, **overrides), REG)
    )


def make_requirement(course_id, required_course_id, requirement_type, **overrides) -> dict:
    return get_success_data(
        api_client.add_course_requirement(
            course_id,
            F.create_course_requirement_payload(required_course_id, requirement_type, **overrides),
            REG,
        )
    )


def make_hold(student_id, hold_type, actor=None, **overrides) -> dict:
    """Place a hold. FINANCIAL -> Bursar, ADVISING -> Advisor unless actor given."""
    headers = actor or (BUR if hold_type == "FINANCIAL" else ADV)
    return get_success_data(api_client.create_hold(F.create_hold_payload(student_id, hold_type, **overrides), headers))


def set_clock(now_iso8601: str) -> None:
    get_success_data(api_client.set_clock({"now_iso8601": now_iso8601}, REG))


def advance_term(term_id, to_status: str) -> dict:
    return get_success_data(api_client.set_term_status(term_id, {"to_status": to_status}, REG))


def set_section_status(section_id, to_status: str) -> dict:
    return get_success_data(api_client.set_section_status(section_id, {"to_status": to_status}, REG))


def section_version(section_id) -> int:
    return get_success_data(api_client.get_section(section_id, REG))["version"]


# ==========================================================================
# Tier 2: Catalog + registration-open scaffolding.
# ==========================================================================
def setup_catalog(course_overrides=None, instructor_overrides=None, term_overrides=None):
    """Program + Instructor + Term(PLANNING) + one Course. Returns a dict of all four."""
    prog = make_program()
    instr = make_instructor(**(instructor_overrides or {}))
    term = make_term(**(term_overrides or {}))
    course = make_course(prog["id"], **(course_overrides or {}))
    return {"program": prog, "instructor": instr, "term": term, "course": course}


def setup_registration_open_section(
    seat_capacity=5,
    waitlist_capacity=0,
    course_overrides=None,
    instructor_overrides=None,
    term_overrides=None,
    section_overrides=None,
):
    """Catalog + one OPEN Section + term advanced to REGISTRATION_OPEN.

    Returns dict: program, instructor, term, course, section.
    """
    cat = setup_catalog(course_overrides, instructor_overrides, term_overrides)
    sec_over = dict(section_overrides or {})
    sec_over.setdefault("seat_capacity", seat_capacity)
    sec_over.setdefault("waitlist_capacity", waitlist_capacity)
    section = make_section(cat["term"]["id"], cat["course"]["id"], cat["instructor"]["id"], **sec_over)
    advance_term(cat["term"]["id"], "REGISTRATION_OPEN")
    cat["section"] = section
    return cat


def setup_student_ready(term_id, program_id, max_credit_hours=12,
                        window_opens_at=WINDOW_OPENS_AT, student_overrides=None,
                        appointment_overrides=None):
    """Create a Student + an EnrollmentAppointment in the term. Returns (student, appointment)."""
    student = make_student(program_id, **(student_overrides or {}))
    appt_over = dict(appointment_overrides or {})
    appt_over.setdefault("max_credit_hours", max_credit_hours)
    appt_over.setdefault("window_opens_at", window_opens_at)
    appt = make_appointment(term_id, student["id"], **appt_over)
    return student, appt


# ==========================================================================
# Tier 1/3: Enrollment shortcuts (the seat-routing engine).
# ==========================================================================
def enroll(term_id, section_id, student_id):
    """Issue an enroll as the owning Student (current section version), return the Enrollment.

    Reads the live section version first so the OCC check passes.
    """
    v = section_version(section_id)
    payload = F.create_enrollment_payload(term_id, section_id, v)
    return get_success_data(api_client.create_enrollment(payload, make_student_headers(student_id)))


def setup_one_enrolled_student(
    clock=CLOCK_REGISTRATION,
    credit_hours=3,
    max_credit_hours=12,
    seat_capacity=5,
    term_overrides=None,
    course_overrides=None,
):
    """Active section + one student ENROLLED in a `credit_hours` course at `clock`.

    Returns dict: program, instructor, term, course, section, student, appointment, enrollment.
    """
    cov = dict(course_overrides or {})
    cov.setdefault("credit_hours", credit_hours)
    base = setup_registration_open_section(
        seat_capacity=seat_capacity, course_overrides=cov, term_overrides=term_overrides
    )
    student, appt = setup_student_ready(base["term"]["id"], base["program"]["id"],
                                        max_credit_hours=max_credit_hours)
    set_clock(clock)
    enr = enroll(base["term"]["id"], base["section"]["id"], student["id"])
    base["student"] = student
    base["appointment"] = appt
    base["enrollment"] = enr
    return base


def setup_enrolled_plus_waitlisted(clock=CLOCK_REGISTRATION, credit_hours=3,
                                   waitlist_capacity=5):
    """Section cap=1, waitlist_cap=`waitlist_capacity`:
    Student A ENROLLED, Student B WAITLISTED (waitlist_position 1).

    Returns dict with program, instructor, term, course, section,
    student_a, appointment_a, enrollment_a, student_b, appointment_b, enrollment_b.
    """
    cov = {"credit_hours": credit_hours}
    base = setup_registration_open_section(
        seat_capacity=1, waitlist_capacity=waitlist_capacity, course_overrides=cov
    )
    a, appt_a = setup_student_ready(base["term"]["id"], base["program"]["id"])
    b, appt_b = setup_student_ready(base["term"]["id"], base["program"]["id"],
                                    appointment_overrides={"priority_tier": 2})
    set_clock(clock)
    enr_a = enroll(base["term"]["id"], base["section"]["id"], a["id"])
    enr_b = enroll(base["term"]["id"], base["section"]["id"], b["id"])
    base.update({
        "student_a": a, "appointment_a": appt_a, "enrollment_a": enr_a,
        "student_b": b, "appointment_b": appt_b, "enrollment_b": enr_b,
    })
    return base


# ==========================================================================
# Tier 3: Grading shortcuts.
# ==========================================================================
def grade(enrollment_id, letter_grade):
    """Enter a final grade as Advisor. Term must be IN_SESSION/CLOSED. Returns the Enrollment."""
    return get_success_data(
        api_client.grade_enrollment(enrollment_id, {"letter_grade": letter_grade}, ADV)
    )


def setup_graded_student(grades, clock=CLOCK_REGISTRATION, max_credit_hours=18, term_overrides=None):
    """Enroll one student into N sections (one per grade) and grade each.

    `grades` is a list of (credit_hours, letter_grade) tuples. Each course gets
    its own section, each taught by its own instructor so the instructor
    double-booking rule never fires, and each on a distinct meeting window so the
    student's schedule never conflicts. Advances the term to IN_SESSION before
    grading.

    The appointment's window opens at the term's `registration_opens_at`, so the
    student is always within their window at `clock` regardless of which term
    deadlines are supplied.

    Returns dict: program, term, student, appointment,
                  instructors (list), sections (list), enrollments (list).
    """
    prog = make_program()
    term = make_term(**(term_overrides or {}))
    sections = []
    instructors = []
    # Distinct windows so no two sections conflict on the student's schedule.
    windows = [
        ("MWF", 540, 590), ("TR", 600, 650), ("S", 660, 710),
        ("MWF", 720, 770), ("TR", 780, 830), ("S", 840, 890),
    ]
    for i, (ch, _g) in enumerate(grades):
        course = make_course(prog["id"], credit_hours=ch)
        instr = make_instructor()  # one instructor per section -> no double-booking
        instructors.append(instr)
        d, s, e = windows[i % len(windows)]
        sec = make_section(term["id"], course["id"], instr["id"],
                           meeting_days=d, meeting_start_min=s, meeting_end_min=e)
        sections.append(sec)
    advance_term(term["id"], "REGISTRATION_OPEN")
    student, appt = setup_student_ready(
        term["id"], prog["id"], max_credit_hours=max_credit_hours,
        window_opens_at=term["registration_opens_at"],
    )
    set_clock(clock)
    enrollments = []
    for sec in sections:
        enrollments.append(enroll(term["id"], sec["id"], student["id"]))
    advance_term(term["id"], "IN_SESSION")
    for enr, (_ch, g) in zip(enrollments, grades):
        grade(enr["id"], g)
    return {
        "program": prog, "term": term,
        "student": student, "appointment": appt,
        "instructors": instructors, "instructor": instructors[0],
        "sections": sections, "enrollments": enrollments,
    }


# ==========================================================================
# Tier 1/5: Drop / withdraw shortcuts.
# ==========================================================================
def drop(enrollment_id, student_id):
    return get_success_data(api_client.drop_enrollment(enrollment_id, make_student_headers(student_id)))


def withdraw(enrollment_id, student_id):
    return get_success_data(api_client.withdraw_enrollment(enrollment_id, make_student_headers(student_id)))


# ==========================================================================
# Prior-term prerequisite setup (graded enrollment in a CLOSED term).
# ==========================================================================
def setup_prior_graded_course(
    program,
    instructor,
    course,
    letter_grade="B",
    term_overrides=None,
):
    """Create a self-contained prior term, enroll a NEW student into `course`,
    grade it `letter_grade`, then CLOSE the term — establishing a graded history
    line usable as prerequisite evidence.

    Returns (student, prior_enrollment, prior_term).
    """
    tov = dict(term_overrides or {})
    tov.setdefault("name", "T0")
    tov.setdefault("registration_opens_at", "2025-08-01T00:00:00Z")
    tov.setdefault("add_deadline", "2025-09-01T00:00:00Z")
    tov.setdefault("drop_deadline", "2025-09-15T00:00:00Z")
    tov.setdefault("withdraw_deadline", "2025-10-15T00:00:00Z")
    prior_term = make_term(**tov)
    sec = make_section(prior_term["id"], course["id"], instructor["id"])
    advance_term(prior_term["id"], "REGISTRATION_OPEN")
    student, _appt = setup_student_ready(prior_term["id"], program["id"],
                                         window_opens_at="2025-08-05T00:00:00Z")
    set_clock("2025-08-10T00:00:00Z")
    enr = enroll(prior_term["id"], sec["id"], student["id"])
    advance_term(prior_term["id"], "IN_SESSION")
    grade(enr["id"], letter_grade)
    advance_term(prior_term["id"], "CLOSED")
    return student, enr, prior_term
