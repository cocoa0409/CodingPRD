"""Composite setup helpers.

Most testable claims require the system to be in a state that takes many API
calls to reach (licensed school, approved course, credentialed instructor,
published offering, enrollments in precise academic/financial states). These
fixtures encapsulate those preambles so tests focus on assertions. All setup
calls use get_success_data() so a setup failure surfaces as a clear error.

Identity threading: Instructor/Proctor/Student calls that are ownership-gated
use make_*_headers(entity_id); staff roles use the shared TEST_USERS constants.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    create_attendance_payload,
    create_course_approval_payload,
    create_course_payload,
    create_enrollment_payload,
    create_exam_attempt_payload,
    create_grant_payload,
    create_instructor_approval_payload,
    create_instructor_payload,
    create_offering_payload,
    create_school_payload,
    create_student_payload,
    decide_approval_payload,
    pay_payload,
    withdraw_payload,
)
from .test_users import (
    TEST_USERS,
    make_instructor_headers,
    make_proctor_headers,
    make_student_headers,
)

DIRECTOR = TEST_USERS["school_director_headers"]
COMMISSION = TEST_USERS["state_commission_headers"]
REGISTRAR = TEST_USERS["registrar_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


# ---------------------------------------------------------------------------
# Tier 1: school and course setup
# ---------------------------------------------------------------------------

def create_school(license_it=False, director_headers=None, **overrides):
    """Register a school; optionally license it. Returns the school dict."""
    hdrs = director_headers or DIRECTOR
    school = get_success_data(api_client.create_school(create_school_payload(**overrides), hdrs))
    if license_it:
        school = get_success_data(api_client.license_school(school["id"], COMMISSION))
    return school


def create_licensed_school(director_headers=None, **overrides):
    """Register + license a school. Returns the LICENSED school dict."""
    return create_school(license_it=True, director_headers=director_headers, **overrides)


def create_course(school_id, director_headers=None, **overrides):
    """Create a DRAFT course under a licensed school."""
    hdrs = director_headers or DIRECTOR
    return get_success_data(api_client.create_course(create_course_payload(school_id, **overrides), hdrs))


def approve_course(course_id, state_code=None, valid_from=None, valid_until=None):
    """Submit + approve a course-approval application. Returns the APPROVED approval."""
    state = state_code or TEST_DEFAULTS["HOME_STATE"]
    approval = get_success_data(
        api_client.create_course_approval(course_id, create_course_approval_payload(state), COMPLIANCE))
    return get_success_data(api_client.decide_approval(
        approval["id"],
        decide_approval_payload(valid_from=valid_from or TEST_DEFAULTS["APPROVAL_VALID_FROM"],
                                valid_until=valid_until or TEST_DEFAULTS["APPROVAL_VALID_UNTIL"]),
        COMMISSION))


def create_active_course(school_id, director_headers=None, state_code=None, **overrides):
    """Create a course, approve it in `state_code`, activate it. Returns the ACTIVE course."""
    course = create_course(school_id, director_headers=director_headers, **overrides)
    approve_course(course["id"], state_code=state_code)
    return get_success_data(api_client.activate_course(course["id"], director_headers or DIRECTOR))


# ---------------------------------------------------------------------------
# Tier 2: instructors and credentialing
# ---------------------------------------------------------------------------

def create_instructor(school_id, **overrides):
    return get_success_data(api_client.create_instructor(create_instructor_payload(school_id, **overrides), REGISTRAR))


def approve_instructor(instructor_id, state_code=None, valid_from=None, valid_until=None):
    """Submit + approve an instructor-approval application. Returns APPROVED approval."""
    state = state_code or TEST_DEFAULTS["HOME_STATE"]
    approval = get_success_data(
        api_client.create_instructor_approval(instructor_id, create_instructor_approval_payload(state), REGISTRAR))
    return get_success_data(api_client.decide_instructor_approval(
        approval["id"],
        decide_approval_payload(valid_from=valid_from or TEST_DEFAULTS["APPROVAL_VALID_FROM"],
                                valid_until=valid_until or TEST_DEFAULTS["APPROVAL_VALID_UNTIL"]),
        COMMISSION))


def create_credentialed_instructor(school_id, states=None, **overrides):
    """Instructor with an APPROVED approval in each state in `states` (default [TX])."""
    instructor = create_instructor(school_id, **overrides)
    for state in (states or [TEST_DEFAULTS["HOME_STATE"]]):
        approve_instructor(instructor["id"], state_code=state)
    return instructor


# ---------------------------------------------------------------------------
# Tier 3: offerings
# ---------------------------------------------------------------------------

def create_offering(course_id, instructor_id, director_headers=None, **overrides):
    """Create a DRAFT offering."""
    return get_success_data(api_client.create_offering(
        create_offering_payload(course_id, instructor_id, **overrides),
        director_headers or DIRECTOR))


def create_published_offering(course_id, instructor_id, director_headers=None, **overrides):
    """Create + publish an offering. Returns the PUBLISHED offering."""
    offering = create_offering(course_id, instructor_id, director_headers=director_headers, **overrides)
    return get_success_data(api_client.publish_offering(offering["id"], director_headers or DIRECTOR))


def create_student(school_id, **overrides):
    return get_success_data(api_client.create_student(create_student_payload(school_id, **overrides), REGISTRAR))


# ---------------------------------------------------------------------------
# Tier 4: enrollments, seat time, exams — the standard teaching scenario
# ---------------------------------------------------------------------------

def setup_publishable_school(course_overrides=None, offering_overrides=None,
                             extra_instructor_states=None, capacity=2):
    """LICENSED school + ACTIVE course (approved in TX) + instructor approved in TX
    (+ extra states) + PUBLISHED offering.

    Returns dict(school, course, instructor, offering, approval).
    """
    school = create_licensed_school()
    course = create_active_course(school["id"], **(course_overrides or {}))
    instructor = create_credentialed_instructor(
        school["id"], states=[TEST_DEFAULTS["HOME_STATE"]] + list(extra_instructor_states or []))
    # Merge capacity into the overrides so an explicit capacity there wins
    # without colliding with the keyword argument (TypeError on duplicate).
    merged_offering = dict(offering_overrides or {})
    merged_offering.setdefault("capacity", capacity)
    offering = create_published_offering(course["id"], instructor["id"], **merged_offering)
    return {"school": school, "course": course, "instructor": instructor, "offering": offering}


def create_enrollment(offering_id, school_id=None, student_payload=None, as_student=False,
                      scholarship_cents=None):
    """Create a student (unless student_payload carries an id) and enroll them.

    Returns (student, enrollment). When as_student=True the enrollment call is
    made by the Student role with X-User-ID == student.id and no student_id body
    field (self-enrollment default path).
    """
    student = get_success_data(api_client.create_student(
        student_payload or create_student_payload(school_id), REGISTRAR))
    kwargs = {}
    if scholarship_cents is not None:
        kwargs["scholarship_cents"] = scholarship_cents
    if as_student:
        payload = create_enrollment_payload(offering_id, **kwargs)
        enrollment = get_success_data(api_client.create_enrollment(payload, make_student_headers(student["id"])))
    else:
        payload = create_enrollment_payload(offering_id, student_id=student["id"], **kwargs)
        enrollment = get_success_data(api_client.create_enrollment(payload, REGISTRAR))
    return student, enrollment


def enroll(offering_id, school_id):
    """Registrar-enrolled fresh student. Returns (student, enrollment)."""
    return create_enrollment(offering_id, school_id)


def enroll_and_pay(offering_id, school_id, amount_cents=None, scholarship_cents=None):
    """Enrollment with payment captured. Returns (student, enrollment)."""
    student, enrollment = create_enrollment(offering_id, school_id,
                                            scholarship_cents=scholarship_cents)
    amount = amount_cents if amount_cents is not None else enrollment["charge_total_cents"]
    enrollment = get_success_data(api_client.pay_enrollment(
        enrollment["id"], pay_payload(amount), REGISTRAR))
    return student, enrollment


def record_attendance(enrollment_id, instructor_id, session_date="2026-09-03", minutes=60):
    """Record a VERIFIED attendance session as the offering's instructor."""
    return get_success_data(api_client.create_attendance_record(
        enrollment_id, create_attendance_payload(session_date=session_date, minutes=minutes),
        make_instructor_headers(instructor_id)))


def enroll_with_seat_time(offering_id, school_id, instructor_id, minutes=60,
                          session_date="2026-09-03", pay=False):
    """Enrollment driven to SEAT_TIME_MET via a single attendance record.

    For required_seat_minutes == 60 courses a single 60-minute record qualifies.
    Returns (student, enrollment).
    """
    if pay:
        student, enrollment = enroll_and_pay(offering_id, school_id)
    else:
        student, enrollment = enroll(offering_id, school_id)
    record_attendance(enrollment["id"], instructor_id, session_date=session_date, minutes=minutes)
    enrollment = get_success_data(api_client.get_enrollment(enrollment["id"], REGISTRAR))
    return student, enrollment


def create_proctor(school_id):
    """A second instructor used as proctor (no approval needed to be assigned)."""
    return create_instructor(school_id)


def schedule_attempt(enrollment_id, proctor_id, scheduled_at=None):
    payload = create_exam_attempt_payload(
        proctor_id, scheduled_at=scheduled_at or TEST_DEFAULTS["EXAM_SCHEDULED_AT"])
    return get_success_data(api_client.create_exam_attempt(enrollment_id, payload, REGISTRAR))


def verify_attempt(attempt_id, proctor_id):
    return get_success_data(api_client.verify_exam_attempt(
        attempt_id, make_proctor_headers(proctor_id)))


def score_attempt(attempt_id, instructor_id, score_pct):
    return get_success_data(api_client.score_exam_attempt(
        attempt_id, {"score_pct": score_pct}, make_instructor_headers(instructor_id)))


def score_attempt_proctored(enrollment_id, instructor_id, proctor_id, score_pct,
                            scheduled_at=None):
    """Schedule -> verify -> score. Returns the SCORED attempt."""
    attempt = schedule_attempt(enrollment_id, proctor_id, scheduled_at=scheduled_at)
    verify_attempt(attempt["id"], proctor_id)
    return score_attempt(attempt["id"], instructor_id, score_pct)


def enrollment_exam_passed(offering_id, school_id, instructor_id, proctor_id,
                           minutes=60, score_pct=90, pay=False):
    """Enrollment driven to EXAM_PASSED. Returns (student, enrollment, attempt)."""
    student, enrollment = enroll_with_seat_time(offering_id, school_id, instructor_id,
                                                minutes=minutes, pay=pay)
    attempt = score_attempt_proctored(enrollment["id"], instructor_id, proctor_id, score_pct)
    enrollment = get_success_data(api_client.get_enrollment(enrollment["id"], REGISTRAR))
    return student, enrollment, attempt


def enrollment_completed(offering_id, school_id, instructor_id, proctor_id,
                         minutes=60, score_pct=90):
    """Enrollment driven to COMPLETED with an issued certificate.

    Returns (student, enrollment, attempt, certificate).
    """
    student, enrollment, attempt = enrollment_exam_passed(
        offering_id, school_id, instructor_id, proctor_id, minutes=minutes, score_pct=score_pct)
    certificate = get_success_data(api_client.issue_certificate(enrollment["id"], REGISTRAR))
    enrollment = get_success_data(api_client.get_enrollment(enrollment["id"], REGISTRAR))
    return student, enrollment, attempt, certificate


# ---------------------------------------------------------------------------
# Tier 5: refunds, reports, sweeps
# ---------------------------------------------------------------------------

def withdraw_and_get_refund(enrollment_id, reason="VOLUNTARY", effective_date=None):
    """Withdraw a PAID enrollment and fetch its auto-created refund request.

    Returns (withdrawn_enrollment, refund_request).
    """
    payload = withdraw_payload(reason=reason)
    if effective_date is not None:
        payload["effective_date"] = effective_date
    enrollment = get_success_data(api_client.withdraw_enrollment(enrollment_id, payload, REGISTRAR))
    data, _meta = validate_paginated(api_client.list_refund_requests(
        REGISTRAR, params={"enrollment_id": enrollment_id}))
    assert len(data) == 1, f"expected exactly one refund request for {enrollment_id}"
    return enrollment, data[0]


def set_clock(to_iso8601):
    return get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, COMPLIANCE))


def run_sweep():
    return get_success_data(api_client.run_regulatory_sweep(COMPLIANCE))


def create_grant(course_id, home_state, recognized_state, expected_course_version):
    return get_success_data(api_client.create_equivalency_grant(
        create_grant_payload(course_id, home_state, recognized_state, expected_course_version),
        COMPLIANCE))


def create_report(school_id, period_start, period_end, **overrides):
    from .factories import create_credit_report_payload
    return get_success_data(api_client.create_credit_report(
        create_credit_report_payload(school_id, period_start, period_end, **overrides),
        COMPLIANCE))


def get_refund_for_enrollment(enrollment_id):
    """Fetch the single refund request of an enrollment (or None)."""
    data, _meta = validate_paginated(api_client.list_refund_requests(
        REGISTRAR, params={"enrollment_id": enrollment_id}))
    return data[0] if data else None


def get_enrollment(enrollment_id):
    return get_success_data(api_client.get_enrollment(enrollment_id, REGISTRAR))


def get_offering(offering_id):
    return get_success_data(api_client.get_offering(offering_id, REGISTRAR))


def get_school(school_id):
    return get_success_data(api_client.get_school(school_id, REGISTRAR))


def get_certificate(certificate_id):
    return get_success_data(api_client.get_certificate(certificate_id, REGISTRAR))


def get_grant(grant_id):
    return get_success_data(api_client.get_equivalency_grant(grant_id, COMPLIANCE))
