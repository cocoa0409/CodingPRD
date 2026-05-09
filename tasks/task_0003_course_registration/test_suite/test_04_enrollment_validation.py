"""Enrollment-request validation cascade and the seat decision (PRD §3.4)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, TEST_USERS,
    create_enrollment_request_payload, make_student_headers,
)
from test_helpers.fixtures import (
    setup_basic_world, setup_open_offering, setup_offering_with_seat_taken,
    create_offering, create_course, create_student, create_lab_equipment,
    create_campus, create_department, create_term_in_planning,
    submit_enrollment, submit_enrollment_success, advance_clock,
    setup_cross_department_world, get_offering,
    get_enrollment_request, list_waitlist,
)


# ─── State precondition (priority 4) ───────────────────────────────────
def test_submit_to_planned_offering_rejected(api):
    """PRD §3.4: "A submission against a CourseOffering whose status is
    anything other than OPEN fails the priority-4 state check with
    ERR_OFFERING_NOT_OPEN (409)."

    Claim: submit to PLANNED offering → ERR_OFFERING_NOT_OPEN.

    # difficulty: cross_entity_state_dependency/cross_entity_enrollment_request_depends_on_course_offering
    """
    world = setup_basic_world()
    course = create_course(world["department"]["id"], credits=3.0)
    offering = create_offering(
        term_id=world["term"]["id"], course_id=course["id"],
        campus_id=world["campus"]["id"], instructor_id=world["instructor"]["id"],
        base_capacity=5,
    )
    # Do not open the offering — it stays in PLANNED.
    res = submit_enrollment(world["student"], offering["id"])
    validate_error(res, "ERR_OFFERING_NOT_OPEN")


def test_submit_to_closed_offering_rejected(api):
    """PRD §3.4: "A submission against a CourseOffering whose status is
    anything other than OPEN fails the priority-4 state check with
    ERR_OFFERING_NOT_OPEN (409)."

    Claim: submit to CLOSED offering → ERR_OFFERING_NOT_OPEN.

    # difficulty: cross_entity_state_dependency/cross_entity_enrollment_request_depends_on_course_offering
    """
    world = setup_basic_world()
    co = setup_open_offering(world, credits=3.0)
    from test_helpers.fixtures import close_offering
    close_offering(co["offering"]["id"])
    res = submit_enrollment(world["student"], co["offering"]["id"])
    validate_error(res, "ERR_OFFERING_NOT_OPEN")


# ─── Ownership (PRD §2.1) ──────────────────────────────────────────────
def test_submit_with_mismatched_user_id_rejected(api):
    """PRD §3.4: "A Student submits an EnrollmentRequest by supplying the
    target student_id (which must equal X-User-ID per §2.1 — a mismatch
    fails with ERR_NOT_OWNER)."

    Claim: X-User-ID != student_id → ERR_NOT_OWNER.
    """
    world = setup_basic_world()
    co = setup_open_offering(world, credits=3.0,
                              scheduled_meetings=[{"day_of_week": 0, "start_minute_of_day": 540, "end_minute_of_day": 600}])
    payload = create_enrollment_request_payload(
        student_id=world["student"]["id"], offering_id=co["offering"]["id"]
    )
    different_student = create_student(world["department"]["id"], world["campus"]["id"], year_in_program=2)
    headers = make_student_headers(different_student["id"])
    res = api.create_enrollment_request(payload, headers)
    validate_error(res, "ERR_NOT_OWNER")


# ─── Cross-department access (priority 6) ──────────────────────────────
def test_cross_department_enrollment_without_grant_rejected(api):
    """PRD §3.4: "Cross-department access (priority 6). When the offering's
    course belongs to a department different from the student's
    program_department_id, an ACTIVE DepartmentAccessGrant whose
    source_department_id is the student's home department and whose
    target_department_id is the course's owning_department_id must exist,
    and the course's category must appear in course_categories_allowed on
    that grant. ... Failure produces ERR_CROSS_DEPARTMENT_ACCESS_DENIED (403)
    and additionally increments the student's fraud_score per §2.11."

    Claim: enrollment against an offering owned by another department, with
    no grant in place, → ERR_CROSS_DEPARTMENT_ACCESS_DENIED.
    """
    world = setup_cross_department_world()
    course_other = create_course(world["department_other"]["id"], credits=3.0)
    offering = create_offering(
        term_id=world["term"]["id"], course_id=course_other["id"],
        campus_id=world["campus"]["id"], instructor_id=world["instructor_other"]["id"],
        base_capacity=5,
    )
    from test_helpers.fixtures import open_offering
    open_offering(offering["id"])
    res = submit_enrollment(world["student"], offering["id"])
    validate_error(res, "ERR_CROSS_DEPARTMENT_ACCESS_DENIED")


# ─── Prerequisite (priority 7) ─────────────────────────────────────────
def test_prerequisite_unsatisfied_rejected(api):
    """PRD §3.4: "Prerequisite satisfaction (priority 7). Every REQUIRED entry
    in the course's prerequisite_course_ids must be satisfied. A prerequisite
    course_id is satisfied when it appears in the student's
    completed_course_ids, or when any course_id in the prerequisite's
    equivalent_course_ids appears there. Failure produces
    ERR_PREREQUISITE_NOT_MET (422)."

    Claim: enroll in a course with REQUIRED prereq the student has not
    completed → ERR_PREREQUISITE_NOT_MET.
    """
    world = setup_basic_world(student_completed_course_ids=[])
    prereq = create_course(world["department"]["id"], credits=3.0, code_prefix="PREREQ")
    course = create_course(
        world["department"]["id"], credits=3.0,
        prerequisite_course_ids=[{"course_id": prereq["id"], "mode": "REQUIRED"}],
        code_prefix="MAIN",
    )
    co = setup_open_offering(world, course=course)
    res = submit_enrollment(world["student"], co["offering"]["id"])
    validate_error(res, "ERR_PREREQUISITE_NOT_MET")


def test_prerequisite_satisfied_via_completion_succeeds(api):
    """PRD §3.4: "A prerequisite course_id is satisfied when it appears in the
    student's completed_course_ids."

    Claim: when the prereq is in completed_course_ids, the enrollment is APPROVED.
    """
    # Build the world step by step so the student is created with the prereq
    # already in their completed_course_ids.
    campus = create_campus()
    dept = create_department(campus["id"])
    instructor = __import__("test_helpers.fixtures", fromlist=["create_professor"]).create_professor(
        dept["id"], is_chair=False
    )
    prereq = create_course(dept["id"], credits=3.0, code_prefix="PREREQ")
    student = create_student(dept["id"], campus["id"], year_in_program=2,
                              completed_course_ids=[prereq["id"]])
    term = create_term_in_planning()
    advance_clock(term["registration_open_at"])

    course = create_course(
        dept["id"], credits=3.0,
        prerequisite_course_ids=[{"course_id": prereq["id"], "mode": "REQUIRED"}],
    )
    offering = create_offering(
        term_id=term["id"], course_id=course["id"],
        campus_id=campus["id"], instructor_id=instructor["id"], base_capacity=5,
    )
    from test_helpers.fixtures import open_offering
    open_offering(offering["id"])

    er = submit_enrollment_success(student, offering["id"])
    assert er["academic_status"] == "APPROVED"


def test_prerequisite_satisfied_via_equivalent_succeeds(api):
    """PRD §3.4: "...or when any course_id in the prerequisite's
    equivalent_course_ids appears there."

    Claim: when an equivalent of the prereq is in completed_course_ids, the
    enrollment is APPROVED (equivalence satisfies prereq).
    """
    campus = create_campus()
    dept = create_department(campus["id"])
    instructor = __import__("test_helpers.fixtures", fromlist=["create_professor"]).create_professor(
        dept["id"], is_chair=False
    )
    # The original prereq, and its equivalent.
    eq = create_course(dept["id"], credits=3.0, code_prefix="EQ")
    prereq = create_course(dept["id"], credits=3.0, code_prefix="PRE",
                            equivalent_course_ids=[eq["id"]])
    student = create_student(dept["id"], campus["id"], year_in_program=2,
                              completed_course_ids=[eq["id"]])  # has equivalent, not original
    term = create_term_in_planning()
    advance_clock(term["registration_open_at"])

    course = create_course(
        dept["id"], credits=3.0,
        prerequisite_course_ids=[{"course_id": prereq["id"], "mode": "REQUIRED"}],
    )
    offering = create_offering(
        term_id=term["id"], course_id=course["id"], campus_id=campus["id"],
        instructor_id=instructor["id"], base_capacity=5,
    )
    from test_helpers.fixtures import open_offering
    open_offering(offering["id"])

    er = submit_enrollment_success(student, offering["id"])
    assert er["academic_status"] == "APPROVED"


# ─── Time conflict (priority 8) ────────────────────────────────────────
def test_time_conflict_overlap_rejected(api):
    """PRD §3.4: "Time-of-week conflict (priority 8). For every offering the
    student is already approved into or waitlisted for in the same term_id,
    the system pairs every meeting in the candidate offering's
    scheduled_meetings with every meeting in the existing offering's
    scheduled_meetings that falls on the same day_of_week. Two meetings
    overlap when each one's start_minute_of_day falls strictly before the
    other one's end_minute_of_day. ... Any overlap fails with
    ERR_TIME_CONFLICT (409)."

    Claim: when two meetings on the same day truly overlap (not just touch),
    the second submission fails with ERR_TIME_CONFLICT.

    # difficulty: resource_temporal_overlap/overlap_student_schedule_half_open_intervals
    """
    world = setup_basic_world()
    # First offering: day=1, 480-600
    co1 = setup_open_offering(world, credits=3.0,
                               scheduled_meetings=[{"day_of_week": 1, "start_minute_of_day": 480, "end_minute_of_day": 600}])
    # Second offering: day=1, 540-660 (overlaps at 540-600)
    co2 = setup_open_offering(world, credits=3.0,
                               scheduled_meetings=[{"day_of_week": 1, "start_minute_of_day": 540, "end_minute_of_day": 660}])
    er1 = submit_enrollment_success(world["student"], co1["offering"]["id"])
    assert er1["academic_status"] == "APPROVED"
    res2 = submit_enrollment(world["student"], co2["offering"]["id"])
    validate_error(res2, "ERR_TIME_CONFLICT")


def test_time_boundary_touching_intervals_do_not_conflict(api):
    """PRD §3.4: "Because intervals are half-open [start, end), two meetings
    that meet exactly at a minute boundary do not overlap."

    Claim: a 480-600 meeting and a 600-720 meeting on the same day do NOT
    conflict; the second submission is APPROVED.

    # difficulty: boundary_precision_check/boundary_time_overlap_half_open_endpoint_enrollment
    """
    world = setup_basic_world()
    co1 = setup_open_offering(world, credits=3.0,
                               scheduled_meetings=[{"day_of_week": 1, "start_minute_of_day": 480, "end_minute_of_day": 600}])
    co2 = setup_open_offering(world, credits=3.0,
                               scheduled_meetings=[{"day_of_week": 1, "start_minute_of_day": 600, "end_minute_of_day": 720}])
    er1 = submit_enrollment_success(world["student"], co1["offering"]["id"])
    assert er1["academic_status"] == "APPROVED"
    er2 = submit_enrollment_success(world["student"], co2["offering"]["id"])
    assert er2["academic_status"] == "APPROVED"


# ─── Lab-equipment conflict (priority 11) ──────────────────────────────
def test_lab_equipment_conflict_within_buffer(api):
    """PRD §3.4: "Lab equipment conflict (priority 11). For every lab_id in the
    candidate offering's requires_lab_equipment_ids, the system looks at
    every OPEN or IN_SESSION offering in the same term that also requires
    that equipment — across all students, not just the requesting student —
    and pairs same-day meetings. Two meetings conflict when each one's
    start_minute_of_day falls strictly before the other one's
    end_minute_of_day plus the per-equipment setup_buffer_minutes. The buffer
    extends both meeting endpoints uniformly. Failure produces
    ERR_LAB_EQUIPMENT_CONFLICT (409)."

    Claim: with a 30-minute setup buffer, an existing 480-600 meeting and a
    new 629-749 meeting (gap = 29 < 30) trigger ERR_LAB_EQUIPMENT_CONFLICT.

    # difficulty: resource_temporal_overlap/overlap_lab_equipment_half_open_with_setup_buffer
    """
    world = setup_basic_world()
    lab = create_lab_equipment(world["campus"]["id"], setup_buffer_minutes=30)
    # Two distinct students so the student-level time conflict (priority 8)
    # is not what fails.
    s1 = create_student(world["department"]["id"], world["campus"]["id"], year_in_program=2,
                         full_name="Student LE A")
    s2 = create_student(world["department"]["id"], world["campus"]["id"], year_in_program=2,
                         full_name="Student LE B")
    # Open co1 and approve s1 BEFORE co2 is opened, otherwise s1's submission
    # would itself observe a lab-conflict against co2 (the priority-11 check
    # scans every OPEN offering using the equipment in this term, regardless
    # of whether anyone is enrolled).
    co1 = setup_open_offering(world, credits=3.0,
                               scheduled_meetings=[{"day_of_week": 1, "start_minute_of_day": 480, "end_minute_of_day": 600}],
                               requires_lab_equipment_ids=[lab["id"]])
    er1 = submit_enrollment_success(s1, co1["offering"]["id"])
    assert er1["academic_status"] == "APPROVED"
    co2 = setup_open_offering(world, credits=3.0,
                               scheduled_meetings=[{"day_of_week": 1, "start_minute_of_day": 629, "end_minute_of_day": 749}],
                               requires_lab_equipment_ids=[lab["id"]])
    res2 = submit_enrollment(s2, co2["offering"]["id"])
    validate_error(res2, "ERR_LAB_EQUIPMENT_CONFLICT")


# ─── Seat decision: APPROVED vs WAITLISTED ─────────────────────────────
def test_first_submission_below_capacity_approved(api):
    """PRD §3.4: "When enrolled_count is strictly less than capacity, the
    request is approved: academic_status is set to APPROVED, the offering's
    enrolled_count is incremented by one, the provisional_credit_charge on
    the request is set to the course's credits, the student's provisional
    credit usage advances by that same amount, the financial_status is moved
    to BILLED."

    Claim: first submission below capacity → APPROVED + BILLED.

    # difficulty: non_linear_state_machine/non_linear_enrollment_request_parallel_dimensions
    """
    world = setup_basic_world(student_year=1)
    co = setup_open_offering(world, credits=3.0, base_capacity=10,
                              scheduled_meetings=[{"day_of_week": 4, "start_minute_of_day": 600, "end_minute_of_day": 720}])
    er = submit_enrollment_success(world["student"], co["offering"]["id"])
    assert er["academic_status"] == "APPROVED"
    assert er["financial_status"] == "BILLED"
    assert float(er["provisional_credit_charge"]) == pytest.approx(3.0, abs=0.01)


def test_submission_when_full_is_waitlisted(api):
    """PRD §3.4: "When enrolled_count is greater than or equal to capacity at
    the instant of decision, the request is waitlisted: academic_status is
    set to WAITLISTED, a priority_score is computed per §3.5 and frozen on
    the request, and a WaitlistEntry is created on the offering. Waitlisting
    is a normal outcome of submission and the response is not an error: the
    request is created with HTTP 201."

    Claim: submission to a full offering → WAITLISTED, with priority_score
    populated and HTTP 201.
    """
    world = setup_basic_world(student_year=2)
    full = setup_offering_with_seat_taken(world)
    er = submit_enrollment_success(world["student"], full["offering"]["id"])
    assert er["academic_status"] == "WAITLISTED"
    assert er["priority_score"] is not None
