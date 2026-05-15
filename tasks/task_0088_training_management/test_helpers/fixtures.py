"""Composite setup helpers — multi-step preambles tests can reuse.

PRD §2.10 logical-clock semantics: the test driver advances the
server clock via POST /training/_clock/advance, and triggers
time-gated transitions via POST /training/_sweep/run. These fixtures
use the shared TrainingAdmin headers for those calls.

IDENTITY THREADING — PRD §2.1: Trainee identity is entity-backed:
"X-User-ID is the `id` of the acting `Trainee` row." Because
ownership checks compare resource.trainee_id against X-User-ID, every
ownership-gated follow-up call (self-enroll, check-in, exam, eval,
cancel own enrollment, renew certificate) MUST be issued with
`make_trainee_headers(trainee['id'])`. Fixtures here accept the
Trainee row (or its id) and thread it through every downstream call.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    blacklist_instructor_payload,
    cancel_session_payload,
    clock_advance_payload,
    create_certificate_template_payload,
    create_check_in_payload,
    create_classroom_payload,
    create_course_category_payload,
    create_course_payload,
    create_credit_adjustment_payload,
    create_credit_pool_payload,
    create_enrollment_payload,
    create_evaluation_payload,
    create_exam_attempt_payload,
    create_instructor_availability_payload,
    create_instructor_payload,
    create_online_room_payload,
    create_session_payload,
    create_trainee_payload,
    emit_event_payload,
    iso_utc,
    renew_certificate_payload,
    submit_exam_attempt_payload,
)
from .test_users import (
    DEPARTMENT_MANAGER_ID,
    TEST_USERS,
    TRAINING_ADMIN_ID,
    make_department_manager_headers,
    make_trainee_headers,
)


# A fixed "epoch" the tests advance from, before any session start.
TEST_EPOCH = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
# Standard session window used by most fixtures.
SESSION_START = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
SESSION_END = datetime(2026, 6, 1, 13, 0, 0, tzinfo=timezone.utc)
ENROLLMENT_DEADLINE = datetime(2026, 5, 31, 23, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _admin_headers() -> Dict[str, str]:
    return TEST_USERS["training_admin_headers"]


def _designer_headers() -> Dict[str, str]:
    return TEST_USERS["course_designer_headers"]


def _manager_headers() -> Dict[str, str]:
    return TEST_USERS["department_manager_headers"]


def _data(resp) -> Dict[str, Any]:
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Clock controls (PRD §2.10)
# ---------------------------------------------------------------------------
def reset_clock_to_epoch() -> str:
    iso = iso_utc(TEST_EPOCH)
    _data(api_client.clock_advance(clock_advance_payload(iso), _admin_headers()))
    return iso


def advance_clock_to(target: datetime) -> str:
    iso = iso_utc(target)
    _data(api_client.clock_advance(clock_advance_payload(iso), _admin_headers()))
    return iso


def run_sweep() -> Dict[str, Any]:
    return _data(api_client.sweep_run(_admin_headers()))


# ---------------------------------------------------------------------------
# Tier 1 — primitive entity creators
# ---------------------------------------------------------------------------
_category_seq = 0


def _next_category_name(prefix: str = "Cat") -> str:
    global _category_seq
    _category_seq += 1
    return f"{prefix}-{_category_seq}"


_course_seq = 0


def _next_course_code(prefix: str = "ENG") -> str:
    """Globally-unique course code matching the PRD regex
    ^[A-Z]{2,6}-[0-9]{3,5}$."""
    global _course_seq
    _course_seq += 1
    return f"{prefix}-{_course_seq:04d}"


_employee_seq = 0


def _next_employee_no() -> str:
    global _employee_seq
    _employee_seq += 1
    return f"EMP-{_employee_seq:05d}"


def create_course_category(
    name: Optional[str] = None,
    parent_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = create_course_category_payload(
        name=name or _next_category_name(), parent_id=parent_id, **overrides,
    )
    return _data(api_client.create_course_category(payload, _admin_headers()))


def create_course(
    category_id: Optional[str] = None,
    *,
    code: Optional[str] = None,
    duration_hours: float = 4.0,
    credit_value: float = 4.0,
    tags: Optional[List[str]] = None,
    is_charged: bool = False,
    prerequisite_course_ids: Optional[List[str]] = None,
    objective: str = "Provide a survey of engineering fundamentals.",
    outline: str = "## Outline\n- Topic 1\n- Topic 2",
    title: str = "Test Course",
    **overrides: Any,
) -> Dict[str, Any]:
    if category_id is None:
        category_id = create_course_category()["id"]
    payload = create_course_payload(
        code=code or _next_course_code(),
        title=title,
        category_id=category_id,
        objective=objective,
        outline=outline,
        duration_hours=duration_hours,
        credit_value=credit_value,
        prerequisite_course_ids=prerequisite_course_ids,
        tags=tags if tags is not None else ["engineering", "core"],
        is_charged=is_charged,
        **overrides,
    )
    return _data(api_client.create_course(payload, _designer_headers()))


def submit_course_for_review(course_id: str) -> Dict[str, Any]:
    return _data(api_client.submit_course_for_review(course_id, _designer_headers()))


def publish_course(course_id: str) -> Dict[str, Any]:
    return _data(api_client.publish_course(course_id, _admin_headers()))


def create_and_publish_course(
    *,
    duration_hours: float = 4.0,
    credit_value: float = 4.0,
    tags: Optional[List[str]] = None,
    is_charged: bool = False,
    prerequisite_course_ids: Optional[List[str]] = None,
    code: Optional[str] = None,
    title: str = "Test Course",
    category_id: Optional[str] = None,
    with_certificate_template: bool = False,
    template_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Course DRAFT -> PENDING_REVIEW -> ON_SHELF.

    When `is_charged=true`, PRD §3.1 demands a CertificateTemplate
    exist before publish — set with_certificate_template=True (or
    create one yourself before calling) or the publish step will
    legitimately fail with ERR_CERT_TEMPLATE_MISSING."""
    course = create_course(
        category_id=category_id,
        code=code,
        title=title,
        duration_hours=duration_hours,
        credit_value=credit_value,
        tags=tags,
        is_charged=is_charged,
        prerequisite_course_ids=prerequisite_course_ids,
    )
    if is_charged or with_certificate_template:
        create_certificate_template(
            course_id=course["id"], **(template_overrides or {}),
        )
    submit_course_for_review(course["id"])
    return publish_course(course["id"])


def create_certificate_template(
    course_id: str,
    *,
    validity_months: int = 12,
    renewal_window_days: int = 30,
    requires_attendance: bool = True,
    requires_exam_pass: bool = True,
) -> Dict[str, Any]:
    payload = create_certificate_template_payload(
        course_id=course_id,
        validity_months=validity_months,
        renewal_window_days=renewal_window_days,
        requires_attendance=requires_attendance,
        requires_exam_pass=requires_exam_pass,
    )
    return _data(api_client.create_certificate_template(payload, _admin_headers()))


def create_instructor(
    *,
    instructor_type: str = "EXTERNAL",
    expertise_tags: Optional[List[str]] = None,
    hourly_rate: float = 200.00,
    travel_cost: float = 50.00,
    full_name: str = "Test Instructor",
    qualifications: Optional[List[str]] = None,
) -> Dict[str, Any]:
    # PRD §3.2: INTERNAL must have hourly_rate=0 and travel_cost=0.
    if instructor_type == "INTERNAL":
        hourly_rate = 0.0
        travel_cost = 0.0
    payload = create_instructor_payload(
        full_name=full_name,
        instructor_type=instructor_type,
        expertise_tags=expertise_tags if expertise_tags is not None else ["engineering", "core"],
        qualifications=qualifications or [],
        hourly_rate=hourly_rate,
        travel_cost=travel_cost,
    )
    return _data(api_client.create_instructor(payload, _admin_headers()))


def create_instructor_availability(
    instructor_id: str,
    start_at: str,
    end_at: str,
    kind: str = "AVAILABLE",
) -> Dict[str, Any]:
    payload = create_instructor_availability_payload(
        start_at=start_at, end_at=end_at, kind=kind,
    )
    return _data(api_client.create_instructor_availability(
        instructor_id, payload, _admin_headers(),
    ))


def create_classroom(
    *,
    name: Optional[str] = None,
    capacity: int = 30,
    setup_buffer_minutes: int = 30,
) -> Dict[str, Any]:
    payload = create_classroom_payload(
        name=name or f"Room-{_next_category_name('CR')}",
        capacity=capacity,
        setup_buffer_minutes=setup_buffer_minutes,
    )
    return _data(api_client.create_classroom(payload, _admin_headers()))


def create_online_room(
    *,
    max_participants: int = 100,
    platform: str = "zoom",
    join_url: Optional[str] = None,
) -> Dict[str, Any]:
    payload = create_online_room_payload(
        platform=platform,
        join_url=join_url or f"https://zoom.example.com/j/{_next_category_name('R')}",
        max_participants=max_participants,
    )
    return _data(api_client.create_online_room(payload, _admin_headers()))


def create_trainee(
    *,
    job_level: int = 5,
    department: str = "engineering",
    full_name: str = "Test Trainee",
    status: str = "ACTIVE",
) -> Dict[str, Any]:
    payload = create_trainee_payload(
        employee_no=_next_employee_no(),
        full_name=full_name,
        department=department,
        job_level=job_level,
    )
    trainee = _data(api_client.create_trainee(payload, _admin_headers()))
    # PRD §2.1 + §3.4 — Trainee status defaults to ACTIVE. If the test
    # wants ON_LEAVE / OFFBOARDED, feed an HR sync event.
    if status != "ACTIVE":
        emit_hr_status_event(trainee["id"], status)
        # Refresh the trainee — admin can read any trainee.
        trainee = _data(api_client.get_trainee(trainee["id"], _admin_headers()))
    return trainee


def emit_hr_status_event(trainee_id: str, status: str) -> Dict[str, Any]:
    """PRD §3.8 / scaffold HR sync: emit employee.updated to flip
    Trainee.status. The implementation may or may not honor this — use
    only for tests that explicitly need a non-ACTIVE trainee."""
    return _data(api_client.emit_event(
        emit_event_payload(
            source_system="HR",
            event_type="employee.updated",
            payload={"trainee_id": trainee_id, "status": status},
        ),
        _admin_headers(),
    ))


def create_credit_pool(
    trainee_id: str,
    *,
    cycle_kind: str = "ANNUAL",
    cycle_start: Optional[str] = None,
    required_credits: float = 20.0,
) -> Dict[str, Any]:
    if cycle_start is None:
        cycle_start = iso_utc(TEST_EPOCH)
    payload = create_credit_pool_payload(
        trainee_id=trainee_id,
        cycle_kind=cycle_kind,
        cycle_start=cycle_start,
        required_credits=required_credits,
    )
    return _data(api_client.create_credit_pool(payload, _admin_headers()))


# ---------------------------------------------------------------------------
# Tier 2 — composite "ready to schedule" scenarios
# ---------------------------------------------------------------------------
def setup_published_course(
    *,
    duration_hours: float = 4.0,
    credit_value: float = 4.0,
    tags: Optional[List[str]] = None,
    is_charged: bool = False,
    prerequisite_course_ids: Optional[List[str]] = None,
    with_certificate_template: bool = False,
    code: Optional[str] = None,
    title: str = "Test Course",
    template_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create + submit + publish a course; return the ON_SHELF course row."""
    if tags is None:
        tags = ["engineering", "core"]
    return create_and_publish_course(
        duration_hours=duration_hours,
        credit_value=credit_value,
        tags=tags,
        is_charged=is_charged,
        prerequisite_course_ids=prerequisite_course_ids,
        code=code,
        title=title,
        with_certificate_template=with_certificate_template,
        template_overrides=template_overrides,
    )


def setup_session_environment(
    *,
    duration_hours: float = 4.0,
    credit_value: float = 4.0,
    tags: Optional[List[str]] = None,
    instructor_type: str = "EXTERNAL",
    hourly_rate: float = 200.00,
    travel_cost: float = 50.00,
    classroom_capacity: int = 30,
    setup_buffer_minutes: int = 30,
    online_room_max_participants: int = 100,
    is_charged: bool = False,
    with_certificate_template: bool = False,
    template_overrides: Optional[Dict[str, Any]] = None,
    course_code: Optional[str] = None,
    availability_start: datetime = SESSION_START - timedelta(hours=2),
    availability_end: datetime = SESSION_END + timedelta(hours=2),
) -> Dict[str, Any]:
    """Course + Instructor (+AVAILABLE window) + Classroom + OnlineRoom,
    all ready for one or more session bookings.

    Returns a dict with keys: course, instructor, classroom, online_room."""
    if tags is None:
        tags = ["engineering", "core"]
    course = setup_published_course(
        duration_hours=duration_hours,
        credit_value=credit_value,
        tags=tags,
        is_charged=is_charged,
        with_certificate_template=with_certificate_template,
        template_overrides=template_overrides,
        code=course_code,
    )
    instructor = create_instructor(
        instructor_type=instructor_type,
        expertise_tags=tags,  # guarantee at least one tag overlap
        hourly_rate=hourly_rate,
        travel_cost=travel_cost,
    )
    create_instructor_availability(
        instructor["id"],
        iso_utc(availability_start),
        iso_utc(availability_end),
        kind="AVAILABLE",
    )
    classroom = create_classroom(
        capacity=classroom_capacity,
        setup_buffer_minutes=setup_buffer_minutes,
    )
    online_room = create_online_room(max_participants=online_room_max_participants)
    return {
        "course": course,
        "instructor": instructor,
        "classroom": classroom,
        "online_room": online_room,
    }


def create_session(
    course: Dict[str, Any],
    instructor: Dict[str, Any],
    *,
    mode: str = "ONSITE",
    classroom: Optional[Dict[str, Any]] = None,
    online_room: Optional[Dict[str, Any]] = None,
    start_at: datetime = SESSION_START,
    end_at: datetime = SESSION_END,
    enrollment_deadline: datetime = ENROLLMENT_DEADLINE,
    capacity: int = 10,
    waitlist_capacity: int = 5,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = create_session_payload(
        course_id=course["id"],
        instructor_id=instructor["id"],
        mode=mode,
        classroom_id=classroom["id"] if classroom is not None else None,
        online_room_id=online_room["id"] if online_room is not None else None,
        start_at=iso_utc(start_at),
        end_at=iso_utc(end_at),
        enrollment_deadline=iso_utc(enrollment_deadline),
        capacity=capacity,
        waitlist_capacity=waitlist_capacity,
        **overrides,
    )
    return _data(api_client.create_session(payload, _admin_headers()))


def setup_open_session(
    *,
    duration_hours: float = 4.0,
    credit_value: float = 4.0,
    capacity: int = 10,
    waitlist_capacity: int = 5,
    tags: Optional[List[str]] = None,
    is_charged: bool = False,
    instructor_type: str = "EXTERNAL",
    hourly_rate: float = 200.00,
    travel_cost: float = 50.00,
    mode: str = "ONSITE",
    with_certificate_template: bool = False,
    template_overrides: Optional[Dict[str, Any]] = None,
    course_code: Optional[str] = None,
    start_at: datetime = SESSION_START,
    end_at: datetime = SESSION_END,
    enrollment_deadline: datetime = ENROLLMENT_DEADLINE,
) -> Dict[str, Any]:
    """Course + Instructor + Classroom + OnlineRoom + Session
    transitioned to ENROLLMENT_OPEN.

    Returns: { course, instructor, classroom, online_room, session }.
    """
    env = setup_session_environment(
        duration_hours=duration_hours,
        credit_value=credit_value,
        tags=tags,
        instructor_type=instructor_type,
        hourly_rate=hourly_rate,
        travel_cost=travel_cost,
        is_charged=is_charged,
        with_certificate_template=with_certificate_template,
        template_overrides=template_overrides,
        course_code=course_code,
        availability_start=start_at - timedelta(hours=2),
        availability_end=end_at + timedelta(hours=2),
    )
    session = create_session(
        env["course"], env["instructor"],
        mode=mode,
        classroom=env["classroom"] if mode in ("ONSITE", "HYBRID") else None,
        online_room=env["online_room"] if mode in ("ONLINE", "HYBRID") else None,
        start_at=start_at,
        end_at=end_at,
        enrollment_deadline=enrollment_deadline,
        capacity=capacity,
        waitlist_capacity=waitlist_capacity,
    )
    # Reset clock to before the deadline so open-enrollment is legal.
    advance_clock_to(min(start_at, enrollment_deadline) - timedelta(days=10))
    session = _data(api_client.open_session_enrollment(
        session["id"], _admin_headers(),
    ))
    env["session"] = session
    return env


# ---------------------------------------------------------------------------
# Tier 3 — Enrollment workflow shortcuts (PRD §3.4)
# ---------------------------------------------------------------------------
def enroll_trainee(
    session_id: str,
    trainee: Dict[str, Any],
    *,
    mode: str = "SELF",
) -> Dict[str, Any]:
    """Enroll a trainee using their own headers (entity-backed identity).

    PRD §2.1 — "When `X-User-Role` is `Trainee`, `X-User-ID` is the
    `id` of the acting `Trainee` row." Therefore self-enrollment must
    pass X-User-ID == trainee['id']."""
    payload = create_enrollment_payload(
        session_id=session_id,
        trainee_id=trainee["id"],
        mode=mode,
    )
    if mode == "SELF":
        headers = make_trainee_headers(trainee["id"])
    else:
        headers = _manager_headers()
    return _data(api_client.create_enrollment(payload, headers))


def approve_enrollment(enrollment_id: str) -> Dict[str, Any]:
    return _data(api_client.approve_enrollment(
        enrollment_id, _manager_headers(),
    ))


def cancel_enrollment(enrollment_id: str, trainee: Dict[str, Any]) -> Dict[str, Any]:
    """Cancel the enrollment as its owning trainee."""
    return _data(api_client.cancel_enrollment(
        enrollment_id, make_trainee_headers(trainee["id"]),
    ))


def cancel_enrollment_as_manager(enrollment_id: str) -> Dict[str, Any]:
    return _data(api_client.cancel_enrollment(
        enrollment_id, _manager_headers(),
    ))


def create_check_in(
    session_id: str,
    enrollment: Dict[str, Any],
    trainee: Dict[str, Any],
    *,
    channel: str = "QR",
    source_value: str = "qr-token-test-001",
) -> Dict[str, Any]:
    """Trainee posts their own check-in. PRD §3.5 + §2.1: Trainee
    ownership compares enrollment.trainee_id against X-User-ID."""
    payload = create_check_in_payload(
        enrollment_id=enrollment["id"],
        channel=channel,
        source_value=source_value,
    )
    return _data(api_client.create_check_in(
        session_id, payload, make_trainee_headers(trainee["id"]),
    ))


# ---------------------------------------------------------------------------
# Tier 4 — Session-completion lifecycle (PRD §3.5)
# ---------------------------------------------------------------------------
def drive_session_to_in_progress(session_id: str, start_at: datetime) -> Dict[str, Any]:
    """Advance clock to start_at + small delta, then run sweep so the
    session moves ENROLLMENT_OPEN -> ENROLLMENT_CLOSED -> IN_PROGRESS
    (PRD §3.3)."""
    advance_clock_to(start_at + timedelta(minutes=1))
    run_sweep()
    return _data(api_client.get_session(session_id, _admin_headers()))


def drive_session_to_completed(session_id: str, end_at: datetime) -> Dict[str, Any]:
    """Advance clock past end_at, run sweep so session is at least
    IN_PROGRESS, then call /complete. PRD §3.5 requires clock >= end_at."""
    advance_clock_to(end_at + timedelta(minutes=1))
    run_sweep()
    return _data(api_client.complete_session(session_id, _admin_headers()))


def submit_exam_for_enrollment(
    enrollment: Dict[str, Any],
    trainee: Dict[str, Any],
    *,
    correctness: Optional[List[bool]] = None,
) -> Dict[str, Any]:
    """Create an ExamAttempt for the enrollment, then submit answers.
    `correctness` is a per-question list of booleans (True = correct).
    If None, all answers are correct.

    Returns the submitted ExamAttempt row."""
    headers = make_trainee_headers(trainee["id"])
    attempt = _data(api_client.create_exam_attempt(
        create_exam_attempt_payload(enrollment_id=enrollment["id"]),
        headers,
    ))
    questions = attempt["questions"]
    answers: List[Dict[str, Any]] = []
    for i, q in enumerate(questions):
        be_correct = True if correctness is None else (
            correctness[i] if i < len(correctness) else False
        )
        if be_correct:
            answers.append({"question_id": q["question_id"],
                            "given_answer": q["correct_answer"]})
        else:
            # Build a wrong answer by appending a sentinel — guaranteed
            # not to equal correct_answer.
            wrong = f"WRONG__{q['correct_answer']}"
            answers.append({"question_id": q["question_id"],
                            "given_answer": wrong})
    return _data(api_client.submit_exam_attempt(
        attempt["id"], submit_exam_attempt_payload(answers), headers,
    ))


def submit_evaluation_for_enrollment(
    enrollment: Dict[str, Any],
    trainee: Dict[str, Any],
    *,
    content_score: int = 5,
    instructor_score: int = 5,
    logistics_score: int = 5,
) -> Dict[str, Any]:
    headers = make_trainee_headers(trainee["id"])
    payload = create_evaluation_payload(
        enrollment_id=enrollment["id"],
        content_score=content_score,
        instructor_score=instructor_score,
        logistics_score=logistics_score,
    )
    return _data(api_client.create_evaluation(payload, headers))


# ---------------------------------------------------------------------------
# Tier 5 — End-to-end "completed enrollment" composite
# ---------------------------------------------------------------------------
def setup_completed_enrollment(
    *,
    duration_hours: float = 4.0,
    credit_value: float = 4.0,
    attendance: str = "PRESENT",
    exam_passed: bool = True,
    is_charged: bool = False,
    with_certificate_template: bool = True,
    template_overrides: Optional[Dict[str, Any]] = None,
    capacity: int = 10,
    waitlist_capacity: int = 5,
    tags: Optional[List[str]] = None,
    job_level: int = 5,
    cycle_start: Optional[str] = None,
    required_credits: float = 20.0,
    start_at: datetime = SESSION_START,
    end_at: datetime = SESSION_END,
    enrollment_deadline: datetime = ENROLLMENT_DEADLINE,
) -> Dict[str, Any]:
    """End-to-end: ON_SHELF course (optionally with template) +
    AVAILABLE instructor + classroom + open session + ACTIVE trainee +
    CONFIRMED enrollment + check-in(s) reaching the requested
    `attendance` + ExamAttempt with passed=exam_passed + Session
    transitioned to COMPLETED.

    Returns: { course, instructor, classroom, online_room, session,
    trainee, credit_pool, enrollment, exam_attempt, certificate_template? }

    `attendance` in {"PRESENT","PARTIAL","ABSENT"} maps to:
      - PRESENT: TWO check-ins evenly spaced across the session
      - PARTIAL: ONE check-in near the midpoint
      - ABSENT:  no check-ins
    """
    if tags is None:
        tags = ["engineering", "core"]
    env = setup_open_session(
        duration_hours=duration_hours,
        credit_value=credit_value,
        capacity=capacity,
        waitlist_capacity=waitlist_capacity,
        tags=tags,
        is_charged=is_charged,
        with_certificate_template=with_certificate_template,
        template_overrides=template_overrides,
        start_at=start_at,
        end_at=end_at,
        enrollment_deadline=enrollment_deadline,
    )
    trainee = create_trainee(job_level=job_level)
    credit_pool = create_credit_pool(
        trainee_id=trainee["id"],
        cycle_kind="ANNUAL",
        cycle_start=cycle_start or iso_utc(TEST_EPOCH),
        required_credits=required_credits,
    )
    enrollment = enroll_trainee(env["session"]["id"], trainee, mode="SELF")
    if is_charged:
        # PRD §3.4: charged courses start in PENDING_APPROVAL.
        enrollment = approve_enrollment(enrollment["id"])

    # Drive into IN_PROGRESS.
    drive_session_to_in_progress(env["session"]["id"], start_at)

    # Record check-ins to reach the requested attendance verdict.
    midpoint = start_at + (end_at - start_at) / 2
    quarter = start_at + (end_at - start_at) / 4
    three_quarter = start_at + (end_at - start_at) * 3 / 4
    if attendance == "PRESENT":
        advance_clock_to(quarter)
        create_check_in(env["session"]["id"], enrollment, trainee,
                        channel="QR", source_value="qr-token-a")
        advance_clock_to(three_quarter)
        create_check_in(env["session"]["id"], enrollment, trainee,
                        channel="QR", source_value="qr-token-b")
    elif attendance == "PARTIAL":
        advance_clock_to(midpoint)
        create_check_in(env["session"]["id"], enrollment, trainee,
                        channel="QR", source_value="qr-token-mid")
    # ABSENT: no check-ins.

    exam_attempt = None
    if attendance != "ABSENT":
        # Submit exam now (before completion).
        exam_attempt = _submit_exam_with_target_pass(
            enrollment, trainee, passed=exam_passed,
        )

    # Complete the session.
    drive_session_to_completed(env["session"]["id"], end_at)

    # Refresh the enrollment via the list endpoint and pick the row
    # belonging to this trainee. PRD §4: list_enrollments accepts
    # session_id+trainee_id filters.
    listing = _data(api_client.list_enrollments(
        _admin_headers(),
        params={"session_id": env["session"]["id"], "trainee_id": trainee["id"]},
    ))
    rows = listing if isinstance(listing, list) else (listing.get("data") or [])
    enrollment_row = next(
        (e for e in rows if e["trainee_id"] == trainee["id"]),
        None,
    )
    if enrollment_row is None:
        # Fallback when the filter is not honored — fetch by session_id only.
        listing = _data(api_client.list_enrollments(
            _admin_headers(),
            params={"session_id": env["session"]["id"]},
        ))
        rows = listing if isinstance(listing, list) else (listing.get("data") or [])
        enrollment_row = next(
            (e for e in rows if e["trainee_id"] == trainee["id"]),
            None,
        )
    env["trainee"] = trainee
    env["credit_pool"] = credit_pool
    env["enrollment"] = enrollment_row or {}
    env["exam_attempt"] = exam_attempt
    return env


def _submit_exam_with_target_pass(
    enrollment: Dict[str, Any],
    trainee: Dict[str, Any],
    *,
    passed: bool,
) -> Dict[str, Any]:
    """Create an ExamAttempt and submit answers, targeting passed=True
    (all correct) or passed=False (all wrong)."""
    if passed:
        return submit_exam_for_enrollment(enrollment, trainee, correctness=None)
    # All wrong:
    headers = make_trainee_headers(trainee["id"])
    attempt = _data(api_client.create_exam_attempt(
        create_exam_attempt_payload(enrollment_id=enrollment["id"]),
        headers,
    ))
    q = attempt["questions"]
    answers = [
        {"question_id": qq["question_id"],
         "given_answer": f"WRONG__{qq['correct_answer']}"}
        for qq in q
    ]
    return _data(api_client.submit_exam_attempt(
        attempt["id"], submit_exam_attempt_payload(answers), headers,
    ))


# ---------------------------------------------------------------------------
# Tier 6 — Difficulty-design fixtures
# ---------------------------------------------------------------------------
def setup_two_confirmed_with_waitlist(
    *,
    capacity: int = 1,
    waitlist_capacity: int = 3,
) -> Dict[str, Any]:
    """Session with capacity=1, waitlist_capacity=3; ONE confirmed
    trainee and TWO waitlisted trainees (positions 1 and 2).

    Returns: { env, trainees=[T1,T2,T3], enrollments=[E1,E2,E3] }."""
    env = setup_open_session(
        capacity=capacity, waitlist_capacity=waitlist_capacity,
    )
    session = env["session"]
    trainees = [create_trainee() for _ in range(3)]
    enrollments = []
    for t in trainees:
        enrollments.append(enroll_trainee(session["id"], t, mode="SELF"))
    return {"env": env, "trainees": trainees, "enrollments": enrollments}


def setup_off_shelf_course() -> Dict[str, Any]:
    """Publish a course, then unpublish so status=OFF_SHELF. Returns
    course + ready-to-use instructor/classroom for session-creation
    rejection tests."""
    env = setup_session_environment()
    # Unpublish.
    course = _data(api_client.unpublish_course(env["course"]["id"], _admin_headers()))
    env["course"] = course
    return env


def setup_certificate_in_expiring_soon(
    *,
    duration_hours: float = 4.0,
    credit_value: float = 4.0,
    validity_months: int = 12,
    renewal_window_days: int = 30,
) -> Dict[str, Any]:
    """End-to-end pipeline that produces a Certificate in
    EXPIRING_SOON status:

      1) Course published with CertificateTemplate
         (requires_attendance/requires_exam_pass = true).
      2) Trainee enrolls in a session; PRESENT attendance + exam pass.
      3) Session completes -> Certificate issued (VALID).
      4) Clock advance to inside renewal_window_days; sweep ->
         EXPIRING_SOON + cert.expiring_soon SyncEvent.

    Returns: setup_completed_enrollment context augmented with
    `certificate` row.
    """
    ctx = setup_completed_enrollment(
        duration_hours=duration_hours,
        credit_value=credit_value,
        attendance="PRESENT",
        exam_passed=True,
        with_certificate_template=True,
        template_overrides={
            "validity_months": validity_months,
            "renewal_window_days": renewal_window_days,
        },
    )
    # Find the just-issued certificate via the listing endpoint.
    listing = _data(api_client.list_certificates(
        _admin_headers(),
        params={"trainee_id": ctx["trainee"]["id"], "status": "VALID"},
    ))
    rows = listing if isinstance(listing, list) else (listing.get("data") or [])
    assert rows, "Expected at least one VALID certificate after completion"
    cert = rows[0]

    # Advance clock into the renewal window. cert.expires_at -
    # renewal_window_days is the lower bound. Advance to expires_at -
    # (renewal_window_days/2) days.
    expires_at = datetime.fromisoformat(cert["expires_at"].replace("Z", "+00:00"))
    target = expires_at - timedelta(days=renewal_window_days // 2 or 1)
    advance_clock_to(target)
    run_sweep()

    # Refresh.
    cert = _data(api_client.get_certificate(cert["id"], _admin_headers()))
    ctx["certificate"] = cert
    return ctx


def setup_course_with_certificate_template(
    *,
    is_charged: bool = False,
    validity_months: int = 12,
    renewal_window_days: int = 30,
    requires_attendance: bool = True,
    requires_exam_pass: bool = True,
    code: Optional[str] = None,
    duration_hours: float = 4.0,
) -> Dict[str, Any]:
    """Course published, certificate template configured. No session."""
    return setup_published_course(
        is_charged=is_charged,
        with_certificate_template=True,
        code=code,
        duration_hours=duration_hours,
        template_overrides={
            "validity_months": validity_months,
            "renewal_window_days": renewal_window_days,
            "requires_attendance": requires_attendance,
            "requires_exam_pass": requires_exam_pass,
        },
    )


def blacklist_existing_instructor(instructor_id: str,
                                  reason: str = "Disciplinary review") -> Dict[str, Any]:
    """PRD §3.2: ACTIVE -> BLACKLISTED."""
    return _data(api_client.blacklist_instructor(
        instructor_id, blacklist_instructor_payload(blacklist_reason=reason),
        _admin_headers(),
    ))


__all__ = [
    "TEST_EPOCH",
    "SESSION_START",
    "SESSION_END",
    "ENROLLMENT_DEADLINE",
    # Clock
    "reset_clock_to_epoch",
    "advance_clock_to",
    "run_sweep",
    # Primitive creators
    "create_course_category",
    "create_course",
    "submit_course_for_review",
    "publish_course",
    "create_and_publish_course",
    "create_certificate_template",
    "create_instructor",
    "create_instructor_availability",
    "create_classroom",
    "create_online_room",
    "create_trainee",
    "emit_hr_status_event",
    "create_credit_pool",
    # Composite
    "setup_published_course",
    "setup_session_environment",
    "create_session",
    "setup_open_session",
    # Enrollment helpers
    "enroll_trainee",
    "approve_enrollment",
    "cancel_enrollment",
    "cancel_enrollment_as_manager",
    "create_check_in",
    # Lifecycle
    "drive_session_to_in_progress",
    "drive_session_to_completed",
    "submit_exam_for_enrollment",
    "submit_evaluation_for_enrollment",
    "setup_completed_enrollment",
    # Difficulty-design
    "setup_two_confirmed_with_waitlist",
    "setup_off_shelf_course",
    "setup_certificate_in_expiring_soon",
    "setup_course_with_certificate_template",
    "blacklist_existing_instructor",
]
