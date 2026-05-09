"""CourseOffering lifecycle and capacity rescaling tests."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, TEST_USERS,
)
from test_helpers.fixtures import (
    setup_basic_world, setup_open_offering, create_offering, open_offering,
    close_offering, get_offering, list_waitlist, get_enrollment_request,
    submit_enrollment_success, list_student_sync_events,
    setup_offering_with_seat_taken, create_course, create_professor,
    advance_clock,
)


def test_offering_created_in_planned(api, registrar_headers):
    """PRD §3.3: "A Registrar creates an offering in PLANNED by supplying the
    term_id, course_id, campus_id where the offering meets, the instructor_id,
    the integer base_capacity (which is set once and immutable), the
    scheduled_meetings array, and the requires_lab_equipment_ids list of
    LabEquipment identifiers used during those meetings. On creation, the
    system populates capacity to equal base_capacity and enrolled_count to zero."

    Claim: POST /course-offerings → status=PLANNED, capacity=base_capacity,
    enrolled_count=0.
    """
    world = setup_basic_world()
    course = create_course(world["department"]["id"], credits=3.0)
    offering = create_offering(
        term_id=world["term"]["id"], course_id=course["id"],
        campus_id=world["campus"]["id"], instructor_id=world["instructor"]["id"],
        base_capacity=12,
    )
    assert offering["status"] == "PLANNED"
    assert offering["base_capacity"] == 12
    assert offering["capacity"] == 12
    assert offering["enrolled_count"] == 0


def test_open_offering_requires_term_in_registration_open(api, registrar_headers):
    """PRD §3.3: "First, the parent Term must be in REGISTRATION_OPEN; otherwise
    the request fails with ERR_TERM_NOT_OPEN_FOR_REGISTRATION (409)."

    Claim: open offering whose Term is in PLANNING → ERR_TERM_NOT_OPEN_FOR_REGISTRATION.
    """
    from test_helpers.fixtures import create_term_in_planning, create_campus, create_department
    campus = create_campus()
    dept = create_department(campus["id"])
    instructor = create_professor(dept["id"], is_chair=False, max_minutes=600)
    term = create_term_in_planning()
    # Note: term is still in PLANNING; do NOT advance the clock.
    course = create_course(dept["id"], credits=3.0)
    offering = create_offering(
        term_id=term["id"], course_id=course["id"],
        campus_id=campus["id"], instructor_id=instructor["id"], base_capacity=5,
    )
    res = api.open_course_offering(offering["id"], registrar_headers)
    validate_error(res, "ERR_TERM_NOT_OPEN_FOR_REGISTRATION")


def test_open_offering_at_instructor_load_boundary_passes(api, registrar_headers):
    """PRD §3.3: "the instructor's accumulated teaching load... plus the new
    offering's per-week meeting minutes must not strictly exceed the
    instructor's max_concurrent_teaching_minutes_per_week. ... The boundary
    case where the new total is exactly equal to the cap is permitted."

    Claim: when total weekly minutes equal the cap exactly, open succeeds.
    Difficulty design covers this with max_concurrent_teaching_minutes_per_week=240.

    # difficulty: boundary_precision_check/boundary_instructor_teaching_load_aggregate_endpoint_open
    """
    from test_helpers.fixtures import create_campus, create_department, create_term_in_planning
    campus = create_campus()
    dept = create_department(campus["id"])
    instructor = create_professor(dept["id"], is_chair=False, rank="ASSISTANT", max_minutes=240)
    term = create_term_in_planning()
    advance_clock(term["registration_open_at"])
    # First offering: 120 min/week, OPEN.
    c1 = create_course(dept["id"], credits=3.0)
    off1 = create_offering(
        term_id=term["id"], course_id=c1["id"], campus_id=campus["id"],
        instructor_id=instructor["id"], base_capacity=5,
        scheduled_meetings=[{"day_of_week": 1, "start_minute_of_day": 480, "end_minute_of_day": 600}],
    )
    open_offering(off1["id"])
    # Second offering: 120 more min/week, total 240 == cap.
    c2 = create_course(dept["id"], credits=3.0)
    off2 = create_offering(
        term_id=term["id"], course_id=c2["id"], campus_id=campus["id"],
        instructor_id=instructor["id"], base_capacity=5,
        scheduled_meetings=[{"day_of_week": 2, "start_minute_of_day": 480, "end_minute_of_day": 600}],
    )
    res = api.open_course_offering(off2["id"], registrar_headers)
    refreshed = validate_success(res, 200)
    assert refreshed["status"] == "OPEN"


def test_open_offering_one_minute_above_load_rejected(api, registrar_headers):
    """PRD §3.3: "If the new total would strictly exceed that cap, the request
    fails with ERR_INSTRUCTOR_TEACHING_LOAD_EXCEEDED (409)."

    Claim: when total weekly minutes would exceed the cap by 1 minute, open fails.

    # difficulty: boundary_precision_check/boundary_instructor_teaching_load_aggregate_endpoint_open
    """
    from test_helpers.fixtures import create_campus, create_department, create_term_in_planning
    campus = create_campus()
    dept = create_department(campus["id"])
    instructor = create_professor(dept["id"], is_chair=False, rank="ASSISTANT", max_minutes=240)
    term = create_term_in_planning()
    advance_clock(term["registration_open_at"])
    # First offering: 120 min, OPEN.
    c1 = create_course(dept["id"], credits=3.0)
    off1 = create_offering(
        term_id=term["id"], course_id=c1["id"], campus_id=campus["id"],
        instructor_id=instructor["id"], base_capacity=5,
        scheduled_meetings=[{"day_of_week": 1, "start_minute_of_day": 480, "end_minute_of_day": 600}],
    )
    open_offering(off1["id"])
    # Second offering: 121 minutes, total would be 241 > 240.
    c2 = create_course(dept["id"], credits=3.0)
    off2 = create_offering(
        term_id=term["id"], course_id=c2["id"], campus_id=campus["id"],
        instructor_id=instructor["id"], base_capacity=5,
        scheduled_meetings=[{"day_of_week": 2, "start_minute_of_day": 480, "end_minute_of_day": 601}],
    )
    res = api.open_course_offering(off2["id"], registrar_headers)
    validate_error(res, "ERR_INSTRUCTOR_TEACHING_LOAD_EXCEEDED")


def test_close_offering_cascades_active_waitlist_to_expired(api, registrar_headers):
    """PRD §3.3: "Closing an offering... carries two cascades: every
    WaitlistEntry for this offering whose status is still ACTIVE is moved to
    EXPIRED, and every EnrollmentRequest for this offering whose
    academic_status is still SUBMITTED is moved to REJECTED."

    Claim: close offering → ACTIVE waitlist entries become EXPIRED.
    """
    world = setup_basic_world(student_year=2)
    full = setup_offering_with_seat_taken(world)
    waitlisted = submit_enrollment_success(world["student"], full["offering"]["id"])
    assert waitlisted["academic_status"] == "WAITLISTED"

    close_offering(full["offering"]["id"])
    waitlist_entries = list_waitlist(full["offering"]["id"])
    for e in waitlist_entries:
        assert e["status"] != "ACTIVE", (
            f"Expected no ACTIVE entries after close; got {e}"
        )


def test_capacity_increase_promotes_waitlisted(api, registrar_headers):
    """PRD §3.3: "If new_capacity is greater than the current capacity, the
    offering's capacity is set to new_capacity and the system attempts to
    promote up to new_capacity minus enrolled_count entries from this
    offering's waitlist. ... Each promotion advances a WaitlistEntry from
    ACTIVE to PROMOTED and the underlying EnrollmentRequest from WAITLISTED
    to APPROVED."

    Claim: PATCH capacity=2 (was 1, enrolled_count=1) promotes the top
    WaitlistEntry; the underlying request becomes APPROVED.
    """
    world = setup_basic_world(student_year=2)
    full = setup_offering_with_seat_taken(world, base_capacity=1)
    er = submit_enrollment_success(world["student"], full["offering"]["id"])
    assert er["academic_status"] == "WAITLISTED"

    current = get_offering(full["offering"]["id"])
    res = api.patch_course_offering_capacity(
        full["offering"]["id"],
        {"new_capacity": 2, "version": current["version"]},
        registrar_headers,
    )
    refreshed = validate_success(res, 200)
    assert refreshed["capacity"] == 2

    er_after = get_enrollment_request(er["id"])
    assert er_after["academic_status"] == "APPROVED"
    assert er_after["financial_status"] == "BILLED"


def test_capacity_reduction_below_enrolled_cancels_lowest_priority(api, registrar_headers):
    """PRD §3.3: "If new_capacity is less than the current capacity and
    new_capacity is also less than the current enrolled_count, the offering
    is over-allocated and the system cancels (enrolled_count minus
    new_capacity) APPROVED enrollments to restore the invariant
    enrolled_count ≤ capacity. The cancellations are taken in lowest-priority
    order — the EnrollmentRequests with the smallest priority_score first,
    with the most recently created request as the secondary tie-break — and
    each canceled request has its academic_status rewritten to REJECTED
    (recorded as cancelled because capacity was reduced), has its
    financial_status reverted to UNBILLED if it was BILLED, and emits a
    CAPACITY_REDUCED_CANCELED SyncEvent to all four downstream systems."

    Claim: PATCH capacity below enrolled_count → lowest-priority request becomes
    REJECTED, financial_status reverts to UNBILLED, CAPACITY_REDUCED_CANCELED
    SyncEvent emitted.

    # difficulty: transitive_cascade/cascade_capacity_reduction_cancels_lowest_priority_depth_3
    """
    world = setup_basic_world(student_year=4)
    co = setup_open_offering(world, credits=3.0, base_capacity=2,
                              scheduled_meetings=[{"day_of_week": 0, "start_minute_of_day": 480, "end_minute_of_day": 600}])
    # S9 (high priority — year 4) and S10 (low priority — year 1)
    from test_helpers.fixtures import create_student
    s_high = create_student(world["department"]["id"], world["campus"]["id"], year_in_program=4,
                             full_name="Higher Priority")
    s_low = create_student(world["department"]["id"], world["campus"]["id"], year_in_program=1,
                            full_name="Lower Priority")
    er_high = submit_enrollment_success(s_high, co["offering"]["id"])
    er_low = submit_enrollment_success(s_low, co["offering"]["id"])
    assert er_high["academic_status"] == "APPROVED"
    assert er_low["academic_status"] == "APPROVED"

    current = get_offering(co["offering"]["id"])
    assert current["enrolled_count"] == 2
    res = api.patch_course_offering_capacity(
        co["offering"]["id"],
        {"new_capacity": 1, "version": current["version"]},
        registrar_headers,
    )
    refreshed = validate_success(res, 200)
    assert refreshed["capacity"] == 1

    # The low-priority enrollment was canceled.
    er_low_after = get_enrollment_request(er_low["id"])
    assert er_low_after["academic_status"] == "REJECTED"
    assert er_low_after["financial_status"] == "UNBILLED"

    # The high-priority enrollment remains.
    er_high_after = get_enrollment_request(er_high["id"])
    assert er_high_after["academic_status"] == "APPROVED"

    # CAPACITY_REDUCED_CANCELED SyncEvent observed for the low-priority student.
    events = list_student_sync_events(s_low["id"])
    types = [e["event_type"] for e in events]
    assert "CAPACITY_REDUCED_CANCELED" in types, (
        f"Expected CAPACITY_REDUCED_CANCELED in {types}"
    )


def test_capacity_reduction_above_enrolled_no_cancellations(api, registrar_headers):
    """PRD §3.3: "If new_capacity is less than the current capacity but is at
    least as large as the current enrolled_count, the capacity is simply
    reduced and no enrollments are touched."

    Claim: PATCH capacity=5 (was 10, enrolled_count=2) → no enrollments touched.
    """
    world = setup_basic_world()
    co = setup_open_offering(world, credits=3.0, base_capacity=10,
                              scheduled_meetings=[{"day_of_week": 0, "start_minute_of_day": 480, "end_minute_of_day": 600}])
    from test_helpers.fixtures import create_student
    s1 = create_student(world["department"]["id"], world["campus"]["id"], year_in_program=2,
                        full_name="Student One")
    s2 = create_student(world["department"]["id"], world["campus"]["id"], year_in_program=2,
                        full_name="Student Two")
    er1 = submit_enrollment_success(s1, co["offering"]["id"])
    er2 = submit_enrollment_success(s2, co["offering"]["id"])

    current = get_offering(co["offering"]["id"])
    res = api.patch_course_offering_capacity(
        co["offering"]["id"],
        {"new_capacity": 5, "version": current["version"]},
        registrar_headers,
    )
    refreshed = validate_success(res, 200)
    assert refreshed["capacity"] == 5
    assert refreshed["enrolled_count"] == 2
    assert get_enrollment_request(er1["id"])["academic_status"] == "APPROVED"
    assert get_enrollment_request(er2["id"])["academic_status"] == "APPROVED"


def test_capacity_patch_stale_version_rejected(api, registrar_headers):
    """PRD §2.6: "Mutating endpoints that target a specific resource by id may
    include the resource's current version number in the request body. If
    version is supplied and does not match the server's current version for
    that resource, the request is rejected with ERR_VERSION_CONFLICT (409)."

    Claim: PATCH capacity with stale version → ERR_VERSION_CONFLICT.
    """
    world = setup_basic_world()
    co = setup_open_offering(world, credits=3.0, base_capacity=10,
                              scheduled_meetings=[{"day_of_week": 3, "start_minute_of_day": 600, "end_minute_of_day": 720}])
    current = get_offering(co["offering"]["id"])
    stale = current["version"]
    # First successful patch increments version.
    api.patch_course_offering_capacity(
        co["offering"]["id"],
        {"new_capacity": 7, "version": stale},
        registrar_headers,
    )
    # Now try with stale version.
    res = api.patch_course_offering_capacity(
        co["offering"]["id"],
        {"new_capacity": 5, "version": stale},
        registrar_headers,
    )
    validate_error(res, "ERR_VERSION_CONFLICT")
