"""Composite setup helpers.

Each test runs against a freshly-restarted, empty server, so every helper builds
its preconditions from scratch using only PRD-declared endpoints. Setup calls use
get_success_data() (lenient 2xx validator) so a setup failure surfaces clearly.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import (
    TEST_USERS, make_student_headers, make_instructor_headers,
)
from .factories import (
    create_course_payload, create_instructor_payload, create_cohort_payload,
    register_student_payload, create_enrollment_payload,
    create_practice_attempt_payload, create_installment_plan_payload,
    create_guarantee_claim_payload,
)

REGISTRAR = TEST_USERS["registrar_headers"]
ANON = TEST_USERS["anonymous_headers"]

BASE_CLOCK = "2026-05-01T00:00:00Z"
DEFAULT_STARTS_AT = "2026-06-01T00:00:00Z"
DEFAULT_ENDS_AT = "2026-06-30T00:00:00Z"


# ---------------------------------------------------------------------------
# Tier 0: low-level single-step helpers (return the created resource dict)
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str):
    """Set the server logical clock."""
    return get_success_data(api_client.set_clock(to_iso8601, REGISTRAR))


def create_course(**overrides) -> dict:
    return get_success_data(api_client.create_course(create_course_payload(**overrides), REGISTRAR))


def create_published_course(**overrides) -> dict:
    """Create a course and publish it. Returns the published course dict."""
    course = create_course(**overrides)
    return get_success_data(api_client.publish_course(course["id"], REGISTRAR))


def create_instructor(**overrides) -> dict:
    return get_success_data(api_client.create_instructor(create_instructor_payload(**overrides), REGISTRAR))


def create_cohort(course_id, **overrides) -> dict:
    return get_success_data(api_client.create_cohort(create_cohort_payload(course_id, **overrides), REGISTRAR))


def register_student(**overrides) -> dict:
    return get_success_data(api_client.register_student(register_student_payload(**overrides), ANON))


# ---------------------------------------------------------------------------
# Tier 1: state progression — scheduled cohort under a published course
# ---------------------------------------------------------------------------

def setup_scheduled_cohort(
    *,
    clock=BASE_CLOCK,
    exam_type="SAT",
    fmt="LIVE",
    list_price_cents=100000,
    baseline_scale_max=1600,
    guarantee_min_delta=200,
    required_practice_tests=1,
    required_attendance_pct=0.5,
    materials_access_days=30,
    seat_capacity=5,
    total_sessions=4,
    starts_at=DEFAULT_STARTS_AT,
    ends_at=DEFAULT_ENDS_AT,
    max_concurrent_cohorts=3,
    instructor_certified=None,
):
    """Clock + published course + certified instructor + a SCHEDULED cohort.

    Returns dict with keys: course, instructor, cohort (each the latest server view),
    and cohort_version (the cohort's version after scheduling — the value a client
    must carry as expected_cohort_version on the first enroll).
    """
    if instructor_certified is None:
        instructor_certified = [exam_type]
    set_clock(clock)
    course = create_published_course(
        exam_type=exam_type, format=fmt, list_price_cents=list_price_cents,
        baseline_scale_max=baseline_scale_max, guarantee_min_delta=guarantee_min_delta,
        required_practice_tests=required_practice_tests,
        required_attendance_pct=required_attendance_pct,
        materials_access_days=materials_access_days,
    )
    instructor = create_instructor(
        certified_exam_types=instructor_certified,
        max_concurrent_cohorts=max_concurrent_cohorts,
    )
    cohort = create_cohort(
        course["id"], seat_capacity=seat_capacity, total_sessions=total_sessions,
        starts_at=starts_at, ends_at=ends_at,
    )
    cohort = get_success_data(api_client.schedule_cohort(cohort["id"], instructor["id"], REGISTRAR))
    return {
        "course": course,
        "instructor": instructor,
        "cohort": cohort,
        "cohort_version": cohort["version"],
    }


# ---------------------------------------------------------------------------
# Tier 2: enrollment + financing + activation
# ---------------------------------------------------------------------------

def enroll_student(cohort_id, *, student=None, expected_cohort_version, coupon_code=None,
                   email=None, full_name="Test Student"):
    """Register a student (if not supplied) and create one enrollment.

    Returns (student, enrollment). Uses the student's own headers (ownership-gated).
    """
    if student is None:
        if email is None:
            email = f"enr-{cohort_id[:8]}-{expected_cohort_version}@x.com"
        student = register_student(email=email, full_name=full_name)
    payload = create_enrollment_payload(
        student["id"], cohort_id, expected_cohort_version,
        **({"coupon_code": coupon_code} if coupon_code is not None else {}),
    )
    enrollment = get_success_data(
        api_client.create_enrollment(payload, make_student_headers(student["id"]))
    )
    return student, enrollment


def finance_and_activate(enrollment, *, num_installments=1, first_payment_cents=None):
    """Create an installment plan, record a settling payment, and activate the enrollment.

    If first_payment_cents is None, pays the full total_financed_cents. Returns
    (plan, activated_enrollment).
    """
    plan = get_success_data(api_client.create_installment_plan(
        create_installment_plan_payload(enrollment["id"], num_installments), REGISTRAR))
    pay = plan["total_financed_cents"] if first_payment_cents is None else first_payment_cents
    plan = get_success_data(api_client.record_payment(plan["id"], pay, REGISTRAR))
    activated = get_success_data(api_client.activate_enrollment(enrollment["id"], REGISTRAR))
    return plan, activated


def setup_active_enrollment(
    *,
    clock=BASE_CLOCK,
    exam_type="SAT",
    fmt="SELF",
    list_price_cents=100000,
    baseline_scale_max=1600,
    guarantee_min_delta=200,
    required_practice_tests=1,
    required_attendance_pct=0.0,
    materials_access_days=30,
    seat_capacity=5,
    total_sessions=4,
    starts_at=DEFAULT_STARTS_AT,
    ends_at=DEFAULT_ENDS_AT,
    coupon_code=None,
    num_installments=1,
    first_payment_cents=None,
    student_email="active@x.com",
):
    """Full chain to an ACTIVE enrollment.

    Returns dict: course, instructor, cohort, student, enrollment (ACTIVE), plan.
    """
    base = setup_scheduled_cohort(
        clock=clock, exam_type=exam_type, fmt=fmt, list_price_cents=list_price_cents,
        baseline_scale_max=baseline_scale_max, guarantee_min_delta=guarantee_min_delta,
        required_practice_tests=required_practice_tests,
        required_attendance_pct=required_attendance_pct,
        materials_access_days=materials_access_days, seat_capacity=seat_capacity,
        total_sessions=total_sessions, starts_at=starts_at, ends_at=ends_at,
    )
    student, enrollment = enroll_student(
        base["cohort"]["id"], expected_cohort_version=base["cohort_version"],
        coupon_code=coupon_code, email=student_email,
    )
    plan, enrollment = finance_and_activate(
        enrollment, num_installments=num_installments, first_payment_cents=first_payment_cents)
    base.update({"student": student, "enrollment": enrollment, "plan": plan})
    return base


# ---------------------------------------------------------------------------
# Tier 3: practice attempts / scoring shortcuts
# ---------------------------------------------------------------------------

def score_attempt(enrollment_id, instructor_id, attempt_type, raw_correct, total_items,
                  student_id):
    """Create + score one attempt (COMPLETED). Returns the scored attempt dict."""
    att = get_success_data(api_client.create_practice_attempt(
        create_practice_attempt_payload(enrollment_id, attempt_type, raw_correct, total_items),
        make_student_headers(student_id)))
    return get_success_data(
        api_client.score_practice_attempt(att["id"], make_instructor_headers(instructor_id)))


def start_attempt(enrollment_id, attempt_type, raw_correct, total_items, student_id):
    """Create one STARTED attempt. Returns the attempt dict."""
    return get_success_data(api_client.create_practice_attempt(
        create_practice_attempt_payload(enrollment_id, attempt_type, raw_correct, total_items),
        make_student_headers(student_id)))


# ---------------------------------------------------------------------------
# Tier 4: conclude / guarantee lifecycle shortcuts
# ---------------------------------------------------------------------------

def conclude_cohort(cohort_id, *, ends_at=DEFAULT_ENDS_AT, started=True, starts_at=DEFAULT_STARTS_AT):
    """Advance the clock and start (if needed) + conclude a SCHEDULED/IN_SESSION cohort.

    Sets clock to starts_at to start, then to ends_at to conclude. Returns concluded cohort.
    """
    if started:
        set_clock(starts_at)
        get_success_data(api_client.start_cohort(cohort_id, REGISTRAR))
    set_clock(ends_at)
    return get_success_data(api_client.conclude_cohort(cohort_id, REGISTRAR))


def setup_concluded_enrollment_with_scores(
    *,
    fmt="SELF",
    guarantee_min_delta=200,
    required_attendance_pct=0.0,
    required_practice_tests=1,
    total_sessions=4,
    diagnostic_raw=50, diagnostic_total=80,
    practice_specs=((550, 800),),
    sessions_attended=None,
    coupon_code=None,
    num_installments=1,
    first_payment_cents=None,
    list_price_cents=100000,
    baseline_scale_max=1600,
    starts_at=DEFAULT_STARTS_AT,
    ends_at=DEFAULT_ENDS_AT,
    student_email="concluded@x.com",
):
    """Full chain: ACTIVE enrollment, scored diagnostic + practice attempts,
    optional attendance, cohort started then concluded (guarantee evaluated).

    practice_specs is a sequence of (raw_correct, total_items) scored in order.
    Returns dict: course, instructor, cohort (CONCLUDED), student, enrollment
    (COMPLETED), plan, diagnostic (attempt), practices (list of attempts).
    """
    base = setup_active_enrollment(
        fmt=fmt, guarantee_min_delta=guarantee_min_delta,
        required_attendance_pct=required_attendance_pct,
        required_practice_tests=required_practice_tests, total_sessions=total_sessions,
        coupon_code=coupon_code, num_installments=num_installments,
        first_payment_cents=first_payment_cents, list_price_cents=list_price_cents,
        baseline_scale_max=baseline_scale_max, starts_at=starts_at, ends_at=ends_at,
        student_email=student_email,
    )
    instructor_id = base["instructor"]["id"]
    student_id = base["student"]["id"]
    enr_id = base["enrollment"]["id"]

    if sessions_attended is not None:
        get_success_data(api_client.record_attendance(
            enr_id, sessions_attended, make_instructor_headers(instructor_id)))

    diagnostic = score_attempt(enr_id, instructor_id, "DIAGNOSTIC",
                               diagnostic_raw, diagnostic_total, student_id)
    practices = []
    for raw, total in practice_specs:
        practices.append(
            score_attempt(enr_id, instructor_id, "PRACTICE", raw, total, student_id))

    cohort = conclude_cohort(base["cohort"]["id"], starts_at=starts_at, ends_at=ends_at)
    enrollment = get_success_data(api_client.get_enrollment(enr_id, REGISTRAR))
    base.update({
        "cohort": cohort, "enrollment": enrollment,
        "diagnostic": diagnostic, "practices": practices,
    })
    return base


def file_and_review_claim(enrollment_id, student_id, resolution):
    """File a guarantee claim and move it to UNDER_REVIEW. Returns the claim (UNDER_REVIEW)."""
    claim = get_success_data(api_client.create_guarantee_claim(
        create_guarantee_claim_payload(enrollment_id, resolution),
        make_student_headers(student_id)))
    claim = get_success_data(api_client.review_guarantee_claim(claim["id"], REGISTRAR))
    return claim


# ---------------------------------------------------------------------------
# Tier 5: seat / waitlist scenarios
# ---------------------------------------------------------------------------

def setup_seat1_with_holder_and_waitlister(
    *,
    exam_type="ACT", fmt="LIVE", baseline_scale_max=36, guarantee_min_delta=3,
    required_attendance_pct=0.5, activate_holder=False, financed_holder=False,
    holder_num_installments=1, holder_first_payment=None, list_price_cents=100000,
):
    """Capacity-1 cohort: student A holds the only seat, student B is WAITLISTED.

    If activate_holder, A is financed + activated (ACTIVE, seats_committed 1) before
    B enrolls. Returns dict with: base keys, student_a, enr_a, plan_a (or None),
    student_b, enr_b, cohort_version_latest (current cohort version after B enrolled).
    """
    base = setup_scheduled_cohort(
        exam_type=exam_type, fmt=fmt, baseline_scale_max=baseline_scale_max,
        guarantee_min_delta=guarantee_min_delta,
        required_attendance_pct=required_attendance_pct, seat_capacity=1,
        list_price_cents=list_price_cents,
    )
    cohort_id = base["cohort"]["id"]
    student_a, enr_a = enroll_student(
        cohort_id, expected_cohort_version=base["cohort_version"], email="seat-a@x.com")
    plan_a = None
    if activate_holder:
        plan_a, enr_a = finance_and_activate(
            enr_a, num_installments=holder_num_installments,
            first_payment_cents=holder_first_payment)
    # Re-read cohort to get current version for B's enroll.
    cohort = get_success_data(api_client.get_cohort(cohort_id, REGISTRAR))
    student_b, enr_b = enroll_student(
        cohort_id, expected_cohort_version=cohort["version"], email="seat-b@x.com")
    cohort = get_success_data(api_client.get_cohort(cohort_id, REGISTRAR))
    base.update({
        "student_a": student_a, "enr_a": enr_a, "plan_a": plan_a,
        "student_b": student_b, "enr_b": enr_b,
        "cohort_version_latest": cohort["version"],
    })
    return base
