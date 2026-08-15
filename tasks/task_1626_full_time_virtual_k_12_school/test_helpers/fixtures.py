"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only.

All six roles use opaque operator identifiers (the PRD performs no
per-resource ownership checks), so the shared TEST_USERS constants are used
throughout.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import DEFAULT_ENROLL_CLOCK
from .factories import (
    create_assessment_window_payload,
    create_attendance_payload,
    create_district_payload,
    create_proctor_assignment_payload,
    create_service_delivery_payload,
    create_stipend_payload,
    create_student_payload,
    create_teacher_assignment_payload,
    create_teacher_payload,
    create_test_site_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]
ENROLLMENT = TEST_USERS["enrollment_officer_headers"]
FINANCE = TEST_USERS["finance_officer_headers"]
ACADEMIC = TEST_USERS["academic_director_headers"]
PROCTOR = TEST_USERS["proctor_coordinator_headers"]
SPECIAL_ED = TEST_USERS["special_ed_coordinator_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation and the logical clock
# ---------------------------------------------------------------------------

def set_clock(to_iso8601):
    """Advance the server's logical clock; fires pending time-driven sweeps."""
    return get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def create_district(district_code="D-100", state_code="CA",
                    funding_rate_cents=500, enrollment_cap=50):
    """Register a district. Returns the district."""
    payload = create_district_payload(
        district_code=district_code, state_code=state_code,
        funding_rate_cents=funding_rate_cents, enrollment_cap=enrollment_cap)
    return get_success_data(api_client.create_district(payload, ADMIN))


def create_student(district_id, legal_name="Test Student",
                   date_of_birth="2012-01-01T00:00:00Z", grade_level=6,
                   special_education_flag=None):
    """Create a student application (born APPLIED). Returns the student."""
    payload = create_student_payload(
        district_id, legal_name=legal_name, date_of_birth=date_of_birth,
        grade_level=grade_level)
    if special_education_flag is not None:
        payload["special_education_flag"] = special_education_flag
    return get_success_data(api_client.create_student(payload, ENROLLMENT))


def get_student(student_id):
    return get_success_data(api_client.get_student(student_id, ENROLLMENT))


def verify_student(student_id):
    """APPLIED -> ELIGIBLE. Returns the updated student."""
    return get_success_data(api_client.verify_residency(student_id, ENROLLMENT))


def enroll_student(student):
    """ELIGIBLE/REENROLL_PENDING -> ENROLLED. Threads the student's current
    version into the OCC field. Returns the updated student."""
    return get_success_data(api_client.enroll_student(
        student["id"], student["version"], ENROLLMENT))


def withdraw_student(student_id, withdrawal_reason):
    """ENROLLED -> WITHDRAWN with the full cascade. Returns the student."""
    return get_success_data(api_client.withdraw_student(
        student_id, withdrawal_reason, ENROLLMENT))


def request_reenrollment(student_id):
    """WITHDRAWN -> REENROLL_PENDING. Returns the updated student."""
    return get_success_data(api_client.request_reenrollment(student_id, ENROLLMENT))


def list_enrollment_terms(student_id):
    """Returns (terms_list, meta) for a student."""
    return validate_paginated(api_client.list_enrollment_terms(student_id, ENROLLMENT))


# ---------------------------------------------------------------------------
# Tier 2: enrolled-student setups (the most common preamble)
# ---------------------------------------------------------------------------

def create_enrolled_student(district=None, enroll_clock=DEFAULT_ENROLL_CLOCK,
                            **student_overrides):
    """District + student walked APPLIED -> ELIGIBLE -> ENROLLED.

    Returns (district, enrolled_student). Pass an existing district dict to
    add a second student to the same district.
    """
    if district is None:
        district = create_district()
    student = create_student(district["id"], **student_overrides)
    student = verify_student(student["id"])
    set_clock(enroll_clock)
    student = enroll_student(student)
    return district, student


def create_special_ed_enrolled_student(district=None,
                                       enroll_clock=DEFAULT_ENROLL_CLOCK,
                                       **student_overrides):
    """Like create_enrolled_student but with special_education_flag=true."""
    student_overrides.setdefault("special_education_flag", True)
    return create_enrolled_student(district=district, enroll_clock=enroll_clock,
                                   **student_overrides)


# ---------------------------------------------------------------------------
# Tier 3: attendance and truancy
# ---------------------------------------------------------------------------

def record_attendance(student_id, attendance_date, synchronous_minutes,
                      engagement_check_ins):
    """Record one day of attendance. Returns the AttendanceRecord."""
    payload = create_attendance_payload(
        student_id, attendance_date=attendance_date,
        synchronous_minutes=synchronous_minutes,
        engagement_check_ins=engagement_check_ins)
    return get_success_data(api_client.create_attendance(payload, ENROLLMENT))


def record_attendance_days(student_id, days):
    """Record a sequence of (date, minutes, check_ins) days.

    Returns the list of created AttendanceRecords in creation order.
    """
    records = []
    for date, minutes, checkins in days:
        records.append(record_attendance(student_id, date, minutes, checkins))
    return records


def setup_student_with_unexcused_absences(absence_count, present_days_between=0):
    """Enrolled student with `absence_count` ABSENT_UNEXCUSED days recorded on
    consecutive calendar days starting 2026-08-03. Optionally interleaves a
    PRESENT day after each absence (used to shape window contents).

    Returns (district, student, absence_records).
    """
    district, student = create_enrolled_student()
    day = 3
    absence_records = []
    for _ in range(absence_count):
        rec = record_attendance(student["id"], f"2026-08-{day:02d}T00:00:00Z", 0, 0)
        absence_records.append(rec)
        day += 1
        for _ in range(present_days_between):
            record_attendance(student["id"], f"2026-08-{day:02d}T00:00:00Z", 300, 3)
            day += 1
    return district, get_student(student["id"]), absence_records


# ---------------------------------------------------------------------------
# Tier 4: stipends
# ---------------------------------------------------------------------------

def create_stipend(student_id, stipend_type="DEVICE", amount_cents=50000):
    """Request a stipend (born REQUESTED). Returns the stipend."""
    payload = create_stipend_payload(student_id, stipend_type=stipend_type,
                                     amount_cents=amount_cents)
    return get_success_data(api_client.create_stipend(payload, FINANCE))


def issue_stipend(stipend_id):
    """REQUESTED -> ISSUED. Returns the updated stipend."""
    return get_success_data(api_client.issue_stipend(stipend_id, FINANCE))


def create_issued_stipend(student_id, stipend_type="DEVICE", amount_cents=50000):
    """Request + issue a stipend for an ENROLLED student. Returns the stipend."""
    stipend = create_stipend(student_id, stipend_type=stipend_type,
                             amount_cents=amount_cents)
    return issue_stipend(stipend["id"])


def get_stipend(stipend_id):
    return get_success_data(api_client.get_stipend(stipend_id, FINANCE))


# ---------------------------------------------------------------------------
# Tier 5: teachers and assignments
# ---------------------------------------------------------------------------

def create_teacher(full_name="Test Teacher", certification_state_codes=None,
                   caseload_cap=30):
    """Register a teacher (born ACTIVE, caseload 0). Returns the teacher."""
    payload = create_teacher_payload(
        full_name=full_name,
        certification_state_codes=certification_state_codes or ["CA"],
        caseload_cap=caseload_cap)
    return get_success_data(api_client.create_teacher(payload, ACADEMIC))


def get_teacher(teacher_id):
    return get_success_data(api_client.get_teacher(teacher_id, ACADEMIC))


def assign_teacher(teacher_id, student_id, subject="MATH"):
    """Create a TeacherAssignment (born ASSIGNED). Returns the assignment."""
    payload = create_teacher_assignment_payload(teacher_id, student_id,
                                                subject=subject)
    return get_success_data(api_client.create_teacher_assignment(payload, ACADEMIC))


# ---------------------------------------------------------------------------
# Tier 6: proctored assessments (windows, sites, bookings)
# ---------------------------------------------------------------------------

def create_assessment_window(assessment_name="Fall Math", subject="MATH",
                             window_start="2026-08-10T08:00:00Z",
                             window_end="2026-08-12T17:00:00Z"):
    """Schedule an assessment window (born SCHEDULED). Returns the window."""
    payload = create_assessment_window_payload(
        assessment_name=assessment_name, subject=subject,
        window_start=window_start, window_end=window_end)
    return get_success_data(api_client.create_assessment_window(payload, PROCTOR))


def create_test_site(site_name="Test Site", state_code="CA", seat_capacity=5):
    """Register a test site. Returns the site."""
    payload = create_test_site_payload(site_name=site_name, state_code=state_code,
                                       seat_capacity=seat_capacity)
    return get_success_data(api_client.create_test_site(payload, PROCTOR))


def get_test_site(site_id):
    return get_success_data(api_client.get_test_site(site_id, PROCTOR))


def book_proctor_seat(student_id, window_id, site):
    """Book a proctored seat, threading the site's current version into the
    OCC field. `site` may be a site dict or a (id, version) tuple.

    Returns the raw response so callers can assert on failures too."""
    if isinstance(site, dict):
        site_id, site_version = site["id"], site["version"]
    else:
        site_id, site_version = site
    payload = create_proctor_assignment_payload(
        student_id, window_id, site_id, site_version)
    return api_client.create_proctor_assignment(payload, PROCTOR)


def setup_booked_proctor_seat(district_state="CA", seat_capacity=5,
                              window_start="2026-08-10T08:00:00Z",
                              window_end="2026-08-12T17:00:00Z"):
    """Enrolled student + site + SCHEDULED window + one BOOKED assignment.

    Returns a dict with district, student, site, window, assignment. The
    returned site dict is refreshed after booking (version/seats_booked moved).
    """
    district, student = create_enrolled_student(
        district=create_district(state_code=district_state))
    site = create_test_site(state_code=district_state, seat_capacity=seat_capacity)
    window = create_assessment_window(window_start=window_start,
                                      window_end=window_end)
    resp = book_proctor_seat(student["id"], window["id"], site)
    assignment = get_success_data(resp)
    site = get_test_site(site["id"])
    return {
        "district": district,
        "student": student,
        "site": site,
        "window": window,
        "assignment": assignment,
    }


# ---------------------------------------------------------------------------
# Tier 7: special-education service deliveries
# ---------------------------------------------------------------------------

def create_service_delivery(student_id, provider_id,
                            service_type="COUNSELING",
                            scheduled_at="2026-08-10T10:00:00Z",
                            duration_minutes=30):
    """Schedule a service session (born SCHEDULED). Returns the delivery."""
    payload = create_service_delivery_payload(
        student_id, provider_id, service_type=service_type,
        scheduled_at=scheduled_at, duration_minutes=duration_minutes)
    return get_success_data(api_client.create_service_delivery(payload, SPECIAL_ED))


def setup_service_delivery(student_state="CA", scheduled_at="2026-08-05T10:00:00Z",
                           duration_minutes=30, service_type="COUNSELING"):
    """Special-ed enrolled student + certified provider + one SCHEDULED
    session. Returns dict with district, student, provider, delivery."""
    district, student = create_special_ed_enrolled_student(
        district=create_district(state_code=student_state))
    provider = create_teacher(certification_state_codes=[student_state])
    delivery = create_service_delivery(
        student["id"], provider["id"], service_type=service_type,
        scheduled_at=scheduled_at, duration_minutes=duration_minutes)
    return {
        "district": district,
        "student": student,
        "provider": provider,
        "delivery": delivery,
    }


def setup_missed_service_delivery(scheduled_at="2026-08-05T10:00:00Z",
                                  duration_minutes=30,
                                  clock_after="2026-08-05T11:00:00Z",
                                  student_state="CA"):
    """A SCHEDULED session whose scheduled end has passed on the logical
    clock, marked MISSED. Returns the setup dict with the MISSED delivery."""
    ctx = setup_service_delivery(student_state=student_state,
                                 scheduled_at=scheduled_at,
                                 duration_minutes=duration_minutes)
    set_clock(clock_after)
    delivery = get_success_data(api_client.mark_service_missed(
        ctx["delivery"]["id"], SPECIAL_ED))
    ctx["delivery"] = delivery
    return ctx
