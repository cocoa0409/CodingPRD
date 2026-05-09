"""Composite setup helpers for the Driving School API.

Fixtures are the place where multi-step preambles live. Tests focus on assertions.

Design principles:
- Every fixture uses get_success_data() (lenient) so setup failures yield
  clear "Setup failed" errors, not assertion noise.
- Identity threading is mandatory: any ownership-gated call uses
  make_student_headers(student["id"]) or make_instructor_headers(instructor["id"]).
- Default time anchor: all "tomorrow"/"today" times are computed off the LOGICAL
  clock, which is what the server uses (PRD §1, §2.6, §3.4). The server starts
  at clock_now=server-start; we drive time only via /_clock/advance.

Time strategy:
- Tests reset the clock implicitly between runs ONLY by using future-relative
  scheduling. Because the test runner spins up a fresh server per session, we
  treat each test as independent. Where a test needs to advance the clock, it
  does so via api.advance_clock(...).
"""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client, ApiClient
from .factories import (
    create_student_payload,
    create_instructor_payload,
    create_vehicle_payload,
    create_course_package_payload,
    create_practice_payload,
    create_exam_payload,
    create_simulator_payload,
    medical_cert_payload,
    select_package_payload,
    check_out_payload,
    record_result_payload,
)
from .test_users import (
    TEST_USERS,
    make_student_headers,
    make_instructor_headers,
    make_admin_headers,
    make_examiner_headers,
)


ADMIN_HEADERS = TEST_USERS["admin_headers"]


# --- Logical-clock anchor helpers ---

def _server_clock_now(api: ApiClient) -> datetime:
    """Read the logical clock from the server's perspective by sweeping a
    no-op AuditLog query. We use the api_request_timestamp meta field as
    a proxy for clock_now.

    Falls back to a default datetime if the server is unreachable; tests will
    fail in a more useful way if so.
    """
    resp = api.list_audit_logs(ADMIN_HEADERS, params={"limit": 1, "offset": 0})
    body = resp.json()
    ts = body.get("meta", {}).get("api_request_timestamp")
    if ts:
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def iso_z(dt: datetime) -> str:
    """Serialize a datetime as ISO 8601 UTC with Z suffix and .000 fractional seconds."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def future_window(api: ApiClient, *, offset_minutes: int, duration_minutes: int) -> Tuple[str, str, datetime]:
    """Return (start_iso, end_iso, start_dt) for a window that starts at
    clock_now + offset_minutes and lasts duration_minutes."""
    now = _server_clock_now(api)
    start = now + timedelta(minutes=offset_minutes)
    end = start + timedelta(minutes=duration_minutes)
    return iso_z(start), iso_z(end), start


# --- Tier 1: state progression — student onboarding ---

def create_pending_student(api: ApiClient = api_client, **overrides) -> Dict[str, Any]:
    payload = create_student_payload(**overrides)
    resp = api.create_student(payload, ADMIN_HEADERS)
    return get_success_data(resp)


def create_active_student(api: ApiClient = api_client, *,
                           package_id: Optional[str] = None,
                           medical_expiry_offset_days: int = 365,
                           **student_overrides) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Walk a student through PENDING_VERIFICATION → ACTIVE.

    Returns (student, package) — package is created if not supplied.
    """
    if package_id is None:
        package = create_default_package(api)
        package_id = package["id"]
    else:
        package = {"id": package_id}

    student = create_pending_student(api, **student_overrides)
    sid = student["id"]

    # verify-identity
    resp = api.verify_identity(sid, ADMIN_HEADERS)
    student = get_success_data(resp)

    # submit-medical-cert with future expiry (relative to logical clock)
    now = _server_clock_now(api)
    expires_on = (now + timedelta(days=medical_expiry_offset_days)).strftime("%Y-%m-%d")
    resp = api.submit_medical_cert(sid, medical_cert_payload(expires_on), ADMIN_HEADERS)
    student = get_success_data(resp)

    # select-package
    resp = api.select_package(sid, select_package_payload(package_id), ADMIN_HEADERS)
    student = get_success_data(resp)

    # sign-contract
    resp = api.sign_contract(sid, ADMIN_HEADERS)
    student = get_success_data(resp)

    return student, package


# --- Tier 2: entity hierarchy ---

def create_default_package(api: ApiClient = api_client, **overrides) -> Dict[str, Any]:
    payload = create_course_package_payload(**overrides)
    resp = api.create_course_package(payload, ADMIN_HEADERS)
    return get_success_data(resp)


def create_active_instructor(api: ApiClient = api_client,
                              vehicle_qualifications: Optional[List[str]] = None,
                              **overrides) -> Dict[str, Any]:
    if vehicle_qualifications is None:
        vehicle_qualifications = ["MANUAL_C1"]
    payload = create_instructor_payload(
        vehicle_qualifications=vehicle_qualifications,
        **overrides,
    )
    resp = api.create_instructor(payload, ADMIN_HEADERS)
    return get_success_data(resp)


def create_active_vehicle(api: ApiClient = api_client, vehicle_type: str = "MANUAL_C1",
                           **overrides) -> Dict[str, Any]:
    payload = create_vehicle_payload(vehicle_type=vehicle_type, **overrides)
    resp = api.create_vehicle(payload, ADMIN_HEADERS)
    return get_success_data(resp)


def setup_basic_scenario(api: ApiClient = api_client) -> Dict[str, Any]:
    """Active student + active instructor + active vehicle + default package.

    Returns a dict with keys: student, instructor, vehicle, package.
    The student and instructor are entity-backed; their .id fields are the
    correct X-User-ID for ownership-gated calls."""
    package = create_default_package(api)
    student, _ = create_active_student(api, package_id=package["id"])
    instructor = create_active_instructor(api)
    vehicle = create_active_vehicle(api)
    return {
        "student": student,
        "instructor": instructor,
        "vehicle": vehicle,
        "package": package,
    }


# --- Tier 3: practice lifecycle shortcuts ---

def book_practice(api: ApiClient, *, student: Dict[str, Any], instructor: Dict[str, Any],
                   vehicle: Dict[str, Any], training_stage: str = "THEORY",
                   start_offset_min: int = 60, duration_min: int = 60,
                   actor_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Book one practice. The actor defaults to Admin so as not to constrain tests."""
    start_iso, end_iso, _ = future_window(api, offset_minutes=start_offset_min, duration_minutes=duration_min)
    payload = create_practice_payload(
        student_id=student["id"],
        instructor_id=instructor["id"],
        vehicle_id=vehicle["id"],
        training_stage=training_stage,
        scheduled_start_at=start_iso,
        scheduled_end_at=end_iso,
    )
    resp = api.book_practice(payload, actor_headers or ADMIN_HEADERS)
    return get_success_data(resp)


def book_practice_at(api: ApiClient, *, student: Dict[str, Any], instructor: Dict[str, Any],
                      vehicle: Dict[str, Any], training_stage: str,
                      start_iso: str, end_iso: str,
                      actor_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Book a practice at explicit ISO timestamps."""
    payload = create_practice_payload(
        student_id=student["id"],
        instructor_id=instructor["id"],
        vehicle_id=vehicle["id"],
        training_stage=training_stage,
        scheduled_start_at=start_iso,
        scheduled_end_at=end_iso,
    )
    resp = api.book_practice(payload, actor_headers or ADMIN_HEADERS)
    return get_success_data(resp)


def book_and_complete_practice(api: ApiClient, *, student: Dict[str, Any], instructor: Dict[str, Any],
                                vehicle: Dict[str, Any], training_stage: str,
                                gps_distance_km: float = 10.0,
                                start_offset_min: int = 60,
                                duration_min: int = 60) -> Dict[str, Any]:
    """Book → check-in → check-out one practice. Advances the logical clock.

    Returns the COMPLETED practice. Side-effect: clock advanced by
    start_offset_min + duration_min.
    """
    practice = book_practice(api,
                             student=student, instructor=instructor, vehicle=vehicle,
                             training_stage=training_stage,
                             start_offset_min=start_offset_min,
                             duration_min=duration_min)

    # advance into check-in window
    api.advance_clock(start_offset_min, ADMIN_HEADERS)

    # check-in as the instructor
    instr_headers = make_instructor_headers(instructor["id"])
    resp = api.check_in_practice(practice["id"], instr_headers)
    get_success_data(resp)

    # advance to scheduled_end_at
    api.advance_clock(duration_min, ADMIN_HEADERS)

    # check-out
    resp = api.check_out_practice(practice["id"],
                                   check_out_payload(gps_distance_km),
                                   instr_headers)
    return get_success_data(resp)


# --- Tier 3b: exam lifecycle shortcuts ---

def book_exam(api: ApiClient, *, student: Dict[str, Any], exam_type: str,
               examiner_id: str = "ex_01",
               start_offset_min: int = 60) -> Dict[str, Any]:
    start_iso, _, _ = future_window(api, offset_minutes=start_offset_min, duration_minutes=60)
    payload = create_exam_payload(
        student_id=student["id"],
        exam_type=exam_type,
        scheduled_at=start_iso,
        examiner_id=examiner_id,
    )
    resp = api.book_exam(payload, ADMIN_HEADERS)
    return get_success_data(resp)


def pass_exam(api: ApiClient, *, exam: Dict[str, Any], examiner_id: str = "ex_01",
               score: int = 95) -> Dict[str, Any]:
    headers = make_examiner_headers(examiner_id)
    resp = api.record_exam_result(exam["id"], record_result_payload(score), headers)
    return get_success_data(resp)


def book_and_pass_exam(api: ApiClient, *, student: Dict[str, Any], exam_type: str,
                        examiner_id: str = "ex_01", score: int = 95) -> Dict[str, Any]:
    exam = book_exam(api, student=student, exam_type=exam_type, examiner_id=examiner_id)
    return pass_exam(api, exam=exam, examiner_id=examiner_id, score=score)


# --- Tier 4: hour accumulation (for stage_min_hours boundary) ---

def accumulate_training_hours(api: ApiClient, *, student: Dict[str, Any], instructor: Dict[str, Any],
                                vehicle: Dict[str, Any], training_stage: str,
                                count: int, minutes_per_session: int = 60,
                                gps_distance_km: float = 10.0) -> List[Dict[str, Any]]:
    """Run N successful practices end-to-end at the given stage, accumulating
    `count * minutes_per_session` validated minutes.

    Each iteration advances the logical clock by ~minutes_per_session+offset.
    Returns the list of COMPLETED practices.

    PRD §3.4 caps the same-instructor daily working-minutes at 480. To keep
    the helper PRD-faithful for callers that pass a single instructor across
    many sessions, we roll the logical clock forward to the next UTC calendar
    day before any session that would push the running per-day total over 480
    minutes for the given instructor.
    """
    completed = []
    # Seed minutes_today from the server so accumulation across separate
    # calls (e.g., BASIC then HIGHWAY) on the same instructor stays under cap.
    inst_now = get_instructor(api, instructor["id"])
    minutes_today = int(inst_now.get("working_minutes_today") or 0)
    for _ in range(count):
        if minutes_today + minutes_per_session > 480:
            # Roll clock to the next UTC calendar date so the next booking lands
            # on a fresh per-day instructor window.
            now = _server_clock_now(api)
            next_midnight = (now + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            advance_by = int((next_midnight - now).total_seconds() // 60) + 1
            api.advance_clock(advance_by, ADMIN_HEADERS)
            minutes_today = 0
        # Each practice: offset=60 → start; +minutes_per_session → end.
        # After check-out, clock has advanced by 60 + minutes_per_session minutes.
        # Add a 30-minute spacer to next start to avoid vehicle buffer collisions.
        practice = book_and_complete_practice(api,
                                                student=student, instructor=instructor, vehicle=vehicle,
                                                training_stage=training_stage,
                                                gps_distance_km=gps_distance_km,
                                                start_offset_min=60,
                                                duration_min=minutes_per_session)
        completed.append(practice)
        # spacer to clear vehicle 15-min buffer + instructor closed interval
        api.advance_clock(30, ADMIN_HEADERS)
        minutes_today += minutes_per_session
    return completed


# --- Tier 5: complaints ---

def file_complaint(api: ApiClient, *, student: Dict[str, Any],
                    category: str = "BILLING",
                    description: str = "Test complaint",
                    instructor_id: Optional[str] = None) -> Dict[str, Any]:
    student_headers = make_student_headers(student["id"])
    payload: Dict[str, Any] = {
        "student_id": student["id"],
        "category": category,
        "description": description,
    }
    if instructor_id is not None:
        payload["instructor_id"] = instructor_id
    resp = api.file_complaint(payload, student_headers)
    return get_success_data(resp)


def file_and_assign_complaint(api: ApiClient, *, student: Dict[str, Any],
                                handler_id: str, handler_role: str = "ComplaintHandler",
                                category: str = "BILLING",
                                description: str = "Test",
                                instructor_id: Optional[str] = None) -> Dict[str, Any]:
    complaint = file_complaint(api, student=student, category=category,
                                 description=description, instructor_id=instructor_id)
    resp = api.assign_handler(complaint["id"],
                                {"handler_id": handler_id, "handler_role": handler_role},
                                ADMIN_HEADERS)
    return get_success_data(resp)


# --- Tier 6: instructor working-minutes accumulation ---

def book_consecutive_practices_today(api: ApiClient, *, instructor: Dict[str, Any],
                                       package: Dict[str, Any], num_slots: int,
                                       slot_minutes: int = 60,
                                       gap_minutes: int = 30,
                                       students: Optional[List[Dict[str, Any]]] = None,
                                       vehicles: Optional[List[Dict[str, Any]]] = None,
                                       training_stage: str = "THEORY") -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Book num_slots back-to-back BOOKED practices on `instructor` today,
    starting at clock_now + 60 minutes, with `gap_minutes` between slots so
    instructor closed-intervals + vehicle 15-min buffer both pass.

    Each slot uses a distinct student + distinct vehicle (created here if not supplied).
    Returns (practices, students, vehicles).
    """
    if students is None:
        students = [create_active_student(api, package_id=package["id"])[0]
                    for _ in range(num_slots)]
    if vehicles is None:
        vehicles = [create_active_vehicle(api) for _ in range(num_slots)]

    # All slots fit within the same UTC calendar date as clock_now+60min (test
    # clocks start near 2024-01-01 00:00 UTC by default, so we have a full day).
    practices = []
    base_offset = 60  # minutes from clock_now to first start
    for i in range(num_slots):
        offset = base_offset + i * (slot_minutes + gap_minutes)
        practices.append(book_practice(api,
                                         student=students[i],
                                         instructor=instructor,
                                         vehicle=vehicles[i],
                                         training_stage=training_stage,
                                         start_offset_min=offset,
                                         duration_min=slot_minutes))
    return practices, students, vehicles


# --- Tier 7: simulator sessions ---

def book_simulator(api: ApiClient, *, student: Dict[str, Any],
                    start_offset_min: int = 60,
                    duration_min: int = 60,
                    actor_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    start_iso, end_iso, _ = future_window(api, offset_minutes=start_offset_min, duration_minutes=duration_min)
    payload = create_simulator_payload(
        student_id=student["id"],
        scheduled_start_at=start_iso,
        scheduled_end_at=end_iso,
    )
    headers = actor_headers or make_student_headers(student["id"])
    resp = api.book_simulator(payload, headers)
    return get_success_data(resp)


# --- Helpers exposed for test convenience ---

def get_student(api: ApiClient, student_id: str) -> Dict[str, Any]:
    """Lenient GET for use inside tests."""
    resp = api.get_student(student_id, ADMIN_HEADERS)
    return get_success_data(resp)


def get_instructor(api: ApiClient, instructor_id: str) -> Dict[str, Any]:
    resp = api.get_instructor(instructor_id, ADMIN_HEADERS)
    return get_success_data(resp)


def get_practice(api: ApiClient, practice_id: str) -> Dict[str, Any]:
    resp = api.get_practice(practice_id, ADMIN_HEADERS)
    return get_success_data(resp)


def get_exam(api: ApiClient, exam_id: str) -> Dict[str, Any]:
    resp = api.get_exam(exam_id, ADMIN_HEADERS)
    return get_success_data(resp)


def get_complaint(api: ApiClient, complaint_id: str) -> Dict[str, Any]:
    resp = api.get_complaint(complaint_id, ADMIN_HEADERS)
    return get_success_data(resp)


def get_training_hours(api: ApiClient, student_id: str) -> Dict[str, Any]:
    resp = api.get_training_hours(student_id, ADMIN_HEADERS)
    return get_success_data(resp)
