"""Composite setup builders.

Every test starts against an empty database, so all preconditions are built from
scratch here using only the endpoints the PRD declares. The builders are ordinary
functions (not pytest fixtures) so that a test can compose them freely and can
still observe the intermediate records they create.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data, validate_success

from . import factories
from .api_client import api_client
from .constants import MAX_ATTENDANCE_HOURS, POST_TEST_HOUR_THRESHOLD
from .test_users import (
    make_center_administrator_headers,
    make_instructor_headers,
    make_program_coordinator_headers,
    make_proctor_headers,
    make_registrar_headers,
    make_state_authority_headers,
    make_student_headers,
)
from .types import (
    AccommodationDecision,
    AllocationVariant,
    CenterDecision,
    IdentityDecision,
    MeasureType,
    OutcomeDecision,
    ProctorDecision,
    ProgramTrack,
    SectionStatus,
    Subtest,
    TestEventPurpose,
    TestForm,
    TestFormat,
    TranscriptDelivery,
    TranscriptDestination,
)

JsonDict = Dict[str, Any]

ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
DATE_FORMAT = "%Y-%m-%d"


# ---------------------------------------------------------------------------
# Instant arithmetic
# ---------------------------------------------------------------------------


def iso(instant: datetime) -> str:
    return instant.strftime(ISO_FORMAT)


def parse_iso(value: str) -> datetime:
    return datetime.strptime(value, ISO_FORMAT)


def shift(value: str, **delta: float) -> str:
    """Return ``value`` moved by the given timedelta keyword arguments."""
    return iso(parse_iso(value) + timedelta(**delta))


def date_of(value: str) -> str:
    """The UTC calendar date of an instant."""
    return value[:10]


def shift_date(value: str, days: int) -> str:
    return (datetime.strptime(value, DATE_FORMAT) + timedelta(days=days)).strftime(DATE_FORMAT)


def at(date: str, hour: int, minute: int = 0) -> str:
    return f"{date}T{hour:02d}:{minute:02d}:00Z"


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


def read_clock(headers: Optional[Dict[str, str]] = None) -> str:
    response = api_client.get_clock(headers=headers or make_state_authority_headers())
    data = get_success_data(response)
    return data["current_utc"] if isinstance(data, dict) else str(data)


def set_clock(current_utc: str, headers: Optional[Dict[str, str]] = None) -> JsonDict:
    response = api_client.set_clock(
        factories.clock_payload(current_utc), headers=headers or make_state_authority_headers()
    )
    return validate_success(response)


def ensure_clock(target: str, headers: Optional[Dict[str, str]] = None) -> str:
    """Move the clock to ``target`` only when that is not a backward step."""
    current = read_clock(headers)
    if target > current:
        set_clock(target, headers)
        return target
    return current


# ---------------------------------------------------------------------------
# Version readers for the three stale-view guards
# ---------------------------------------------------------------------------


def current_exam_session_version(session_id: str) -> int:
    response = api_client.get_exam_session(session_id, headers=make_state_authority_headers())
    return get_success_data(response)["version"]


def current_enrollment_version(enrollment_id: str) -> int:
    response = api_client.get_enrollment(enrollment_id, headers=make_state_authority_headers())
    return get_success_data(response)["version"]


def current_funding_period_version(period_id: str) -> int:
    response = api_client.get_funding_period(period_id, headers=make_state_authority_headers())
    return get_success_data(response)["version"]


# ---------------------------------------------------------------------------
# Learner intake
# ---------------------------------------------------------------------------


def create_student(**overrides: Any) -> JsonDict:
    """A learner at INTAKE_STARTED with an empty voucher ledger."""
    response = api_client.create_student(
        factories.create_student_payload(**overrides),
        headers=make_program_coordinator_headers(),
    )
    return validate_success(response, expected_status=201)


def create_oriented_student(**overrides: Any) -> JsonDict:
    """A learner advanced from INTAKE_STARTED to ORIENTED."""
    student = create_student(**overrides)
    response = api_client.complete_orientation(student["id"], headers=make_registrar_headers())
    return validate_success(response)


def schedule_test_event(
    student_id: str,
    scheduled_for: str,
    purpose: str = TestEventPurpose.PRE_TEST,
    test_form: str = TestForm.CASAS_R_900,
    enrollment_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> JsonDict:
    payload = factories.create_test_event_payload(
        student_id, scheduled_for, purpose=purpose, test_form=test_form
    )
    if enrollment_id is not None:
        payload["enrollment_id"] = enrollment_id
    response = api_client.create_test_event(payload, headers=headers or make_registrar_headers())
    return validate_success(response, expected_status=201)


def score_test_event(test_event_id: str, scale_score: int) -> JsonDict:
    response = api_client.score_test_event(
        test_event_id,
        factories.score_test_event_payload(scale_score),
        headers=make_instructor_headers(),
    )
    return validate_success(response)


def create_placed_student(
    scale_score: int = 205,
    test_form: str = TestForm.CASAS_R_900,
    pre_test_at: str = "2026-08-03T09:00:00Z",
    **overrides: Any,
) -> JsonDict:
    """A learner at PLACED, with the placement drawn from a scored pre-test.

    Returns ``{"student", "student_id", "pre_test", "pre_test_at"}``.
    """
    student = create_oriented_student(**overrides)
    pre_test = schedule_test_event(student["id"], pre_test_at, test_form=test_form)
    ensure_clock(pre_test_at)
    scored = score_test_event(pre_test["id"], scale_score)
    refreshed = get_success_data(
        api_client.get_student(student["id"], headers=make_program_coordinator_headers())
    )
    return {
        "student": refreshed,
        "student_id": student["id"],
        "pre_test": scored,
        "pre_test_at": pre_test_at,
    }


def grant_voucher(student_id: str, delta_cents: int) -> JsonDict:
    response = api_client.adjust_voucher(
        student_id,
        factories.voucher_adjustment_payload(delta_cents),
        headers=make_program_coordinator_headers(),
    )
    return validate_success(response)


def read_student(student_id: str, headers: Optional[Dict[str, str]] = None) -> JsonDict:
    response = api_client.get_student(
        student_id, headers=headers or make_program_coordinator_headers()
    )
    return validate_success(response)


# ---------------------------------------------------------------------------
# Sections, enrollment and attendance
# ---------------------------------------------------------------------------


def create_section(status: str = SectionStatus.PLANNED, **overrides: Any) -> JsonDict:
    """A section created PLANNED and then driven to ``status``."""
    response = api_client.create_class_section(
        factories.create_class_section_payload(**overrides),
        headers=make_program_coordinator_headers(),
    )
    section = validate_success(response, expected_status=201)
    path = {
        SectionStatus.PLANNED: [],
        SectionStatus.OPEN: [SectionStatus.OPEN],
        SectionStatus.IN_SESSION: [SectionStatus.OPEN, SectionStatus.IN_SESSION],
        SectionStatus.CLOSED: [SectionStatus.OPEN, SectionStatus.CLOSED],
    }[status]
    for target in path:
        section = transition_section(section["id"], target)
    return section


def transition_section(section_id: str, target_status: str) -> JsonDict:
    response = api_client.transition_class_section(
        section_id,
        factories.section_transition_payload(target_status),
        headers=make_program_coordinator_headers(),
    )
    return validate_success(response)


def enroll(student_id: str, class_section_id: str) -> JsonDict:
    response = api_client.create_enrollment(
        factories.create_enrollment_payload(student_id, class_section_id),
        headers=make_program_coordinator_headers(),
    )
    return validate_success(response, expected_status=201)


def split_hours(total_hours: float) -> List[float]:
    """Split a target into daily postings no larger than the daily maximum."""
    chunks: List[float] = []
    remaining = round(float(total_hours), 2)
    while remaining > 0:
        chunk = MAX_ATTENDANCE_HOURS if remaining >= MAX_ATTENDANCE_HOURS else remaining
        chunks.append(round(chunk, 2))
        remaining = round(remaining - chunk, 2)
    return chunks


def post_attendance(
    enrollment_id: str,
    attendance_date: str,
    hours: float,
    headers: Optional[Dict[str, str]] = None,
) -> JsonDict:
    ensure_clock(at(attendance_date, 12))
    response = api_client.create_attendance_entry(
        enrollment_id,
        factories.create_attendance_entry_payload(attendance_date, hours),
        headers=headers or make_instructor_headers(),
    )
    return validate_success(response, expected_status=201)


def post_instructional_hours(
    enrollment_id: str,
    total_hours: float,
    first_date: str = "2026-08-03",
    headers: Optional[Dict[str, str]] = None,
) -> List[JsonDict]:
    """Post ``total_hours`` as consecutive daily entries from ``first_date``."""
    chunks = split_hours(total_hours)
    dates = [shift_date(first_date, offset) for offset in range(len(chunks))]
    if dates:
        ensure_clock(at(dates[-1], 12))
    entries = []
    for date, chunk in zip(dates, chunks):
        entries.append(post_attendance(enrollment_id, date, chunk, headers=headers))
    return entries


def void_attendance(
    entry_id: str,
    enrollment_id: str,
    void_reason: str = "Posted in error",
    expected_enrollment_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> JsonDict:
    version = (
        expected_enrollment_version
        if expected_enrollment_version is not None
        else current_enrollment_version(enrollment_id)
    )
    response = api_client.void_attendance_entry(
        entry_id,
        factories.void_attendance_payload(version, void_reason=void_reason),
        headers=headers or make_instructor_headers(),
    )
    return validate_success(response)


def setup_enrollment_with_hours(
    total_hours: float = POST_TEST_HOUR_THRESHOLD,
    program_track: str = ProgramTrack.HSE_PREP,
    scale_score: int = 205,
    first_date: str = "2026-08-03",
    section_overrides: Optional[JsonDict] = None,
    **student_overrides: Any,
) -> JsonDict:
    """A placed learner enrolled in an OPEN section with posted hours.

    Returns ``{"student_id", "student", "section", "enrollment", "entries",
    "pre_test", "pre_test_at"}``.
    """
    placed = create_placed_student(
        scale_score=scale_score, primary_track=program_track, **student_overrides
    )
    section = create_section(
        status=SectionStatus.OPEN, program_track=program_track, **(section_overrides or {})
    )
    enrollment = enroll(placed["student_id"], section["id"])
    entries = (
        post_instructional_hours(enrollment["id"], total_hours, first_date=first_date)
        if total_hours
        else []
    )
    return {
        "student_id": placed["student_id"],
        "student": read_student(placed["student_id"]),
        "pre_test": placed["pre_test"],
        "pre_test_at": placed["pre_test_at"],
        "section": get_success_data(
            api_client.get_class_section(section["id"], headers=make_program_coordinator_headers())
        ),
        "enrollment": get_success_data(
            api_client.get_enrollment(enrollment["id"], headers=make_program_coordinator_headers())
        ),
        "entries": entries,
    }


def score_post_test(
    student_id: str,
    enrollment_id: str,
    scheduled_for: str,
    scale_score: int,
    test_form: str = TestForm.CASAS_R_900,
) -> JsonDict:
    """Schedule and score one post-test, moving the clock onto its instant."""
    ensure_clock(shift(scheduled_for, hours=-1))
    event = schedule_test_event(
        student_id,
        scheduled_for,
        purpose=TestEventPurpose.POST_TEST,
        test_form=test_form,
        enrollment_id=enrollment_id,
    )
    ensure_clock(scheduled_for)
    return score_test_event(event["id"], scale_score)


def read_skill_gain(
    student_id: str,
    variant: Optional[str] = None,
    funding_period_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> JsonDict:
    params: JsonDict = {}
    if variant is not None:
        params["variant"] = variant
    if funding_period_id is not None:
        params["funding_period_id"] = funding_period_id
    response = api_client.get_skill_gain(
        student_id, headers=headers or make_program_coordinator_headers(), params=params or None
    )
    return validate_success(response)


# ---------------------------------------------------------------------------
# Testing centres, rooms and proctors
# ---------------------------------------------------------------------------


def create_center(**overrides: Any) -> JsonDict:
    """A centre application sitting at APPLIED."""
    response = api_client.create_testing_center(
        factories.create_testing_center_payload(**overrides),
        headers=make_state_authority_headers(),
    )
    return validate_success(response, expected_status=201)


def decide_center(center_id: str, decision: str) -> JsonDict:
    response = api_client.decide_center_authorization(
        center_id,
        factories.center_authorization_decision_payload(decision),
        headers=make_state_authority_headers(),
    )
    return validate_success(response)


def create_authorized_center(
    decision: str = CenterDecision.GRANT_FULL, **overrides: Any
) -> JsonDict:
    center = create_center(**overrides)
    return decide_center(center["id"], decision)


def suspend_center(center_id: str, suspended_reason: str = "State audit finding") -> JsonDict:
    response = api_client.suspend_center(
        center_id,
        factories.suspend_center_payload(suspended_reason),
        headers=make_state_authority_headers(),
    )
    return validate_success(response)


def create_room(center_id: str, **overrides: Any) -> JsonDict:
    response = api_client.create_testing_room(
        center_id,
        factories.create_testing_room_payload(**overrides),
        headers=make_center_administrator_headers(center_id),
    )
    return validate_success(response, expected_status=201)


def retire_room(center_id: str, room_id: str, service_note: str = "Ceiling repair") -> JsonDict:
    response = api_client.take_room_out_of_service(
        room_id,
        factories.out_of_service_payload(service_note),
        headers=make_center_administrator_headers(center_id),
    )
    return validate_success(response)


def create_proctor(center_id: str, **overrides: Any) -> JsonDict:
    """A proctor candidate sitting at PENDING."""
    response = api_client.create_proctor(
        center_id,
        factories.create_proctor_payload(**overrides),
        headers=make_center_administrator_headers(center_id),
    )
    return validate_success(response, expected_status=201)


def decide_proctor(
    proctor_id: str,
    decision: str = ProctorDecision.CERTIFY,
    certification_expires_at: Optional[str] = "2027-06-30T00:00:00Z",
) -> JsonDict:
    response = api_client.decide_proctor_certification(
        proctor_id,
        factories.proctor_certification_decision_payload(
            decision, certification_expires_at=certification_expires_at
        ),
        headers=make_state_authority_headers(),
    )
    return validate_success(response)


def create_certified_proctor(
    center_id: str,
    certification_expires_at: str = "2027-06-30T00:00:00Z",
    **overrides: Any,
) -> JsonDict:
    proctor = create_proctor(center_id, **overrides)
    return decide_proctor(
        proctor["id"],
        ProctorDecision.CERTIFY,
        certification_expires_at=certification_expires_at,
    )


def setup_center_with_room_and_proctor(
    decision: str = CenterDecision.GRANT_FULL,
    seat_capacity: int = 20,
    turnaround_buffer_minutes: Optional[int] = None,
    daily_hour_cap: Optional[float] = None,
    certification_expires_at: str = "2027-06-30T00:00:00Z",
    **center_overrides: Any,
) -> JsonDict:
    """A decided centre with one ACTIVE room and one CERTIFIED proctor.

    Returns ``{"center", "center_id", "room", "room_id", "proctor", "proctor_id",
    "admin_headers", "proctor_headers"}``.
    """
    center = create_authorized_center(decision, **center_overrides)
    room_overrides: JsonDict = {"seat_capacity": seat_capacity}
    if turnaround_buffer_minutes is not None:
        room_overrides["turnaround_buffer_minutes"] = turnaround_buffer_minutes
    room = create_room(center["id"], **room_overrides)
    proctor_overrides: JsonDict = {}
    if daily_hour_cap is not None:
        proctor_overrides["daily_hour_cap"] = daily_hour_cap
    proctor = create_certified_proctor(
        center["id"], certification_expires_at=certification_expires_at, **proctor_overrides
    )
    return {
        "center": center,
        "center_id": center["id"],
        "room": room,
        "room_id": room["id"],
        "proctor": proctor,
        "proctor_id": proctor["id"],
        "admin_headers": make_center_administrator_headers(center["id"]),
        "proctor_headers": make_proctor_headers(proctor["id"]),
    }


# ---------------------------------------------------------------------------
# Exam sittings
# ---------------------------------------------------------------------------


def create_session(
    center_id: str,
    room_id: str,
    starts_at: str,
    ends_at: str,
    subtest: str = Subtest.MATH,
    requested_seats: int = 5,
    **overrides: Any,
) -> JsonDict:
    response = api_client.create_exam_session(
        factories.create_exam_session_payload(
            room_id,
            starts_at,
            ends_at,
            subtest=subtest,
            requested_seats=requested_seats,
            **overrides,
        ),
        headers=make_center_administrator_headers(center_id),
    )
    return validate_success(response, expected_status=201)


def assign_session_proctor(center_id: str, session_id: str, proctor_id: str) -> JsonDict:
    response = api_client.assign_proctor(
        session_id,
        factories.proctor_assignment_payload(proctor_id),
        headers=make_center_administrator_headers(center_id),
    )
    return validate_success(response)


def cancel_session(
    center_id: str, session_id: str, cancel_reason: str = "Centre closure"
) -> JsonDict:
    response = api_client.cancel_exam_session(
        session_id,
        factories.cancel_exam_session_payload(cancel_reason),
        headers=make_center_administrator_headers(center_id),
    )
    return validate_success(response)


def read_session(session_id: str, headers: Optional[Dict[str, str]] = None) -> JsonDict:
    response = api_client.get_exam_session(
        session_id, headers=headers or make_state_authority_headers()
    )
    return validate_success(response)


def setup_scheduled_session(
    starts_at: str = "2026-09-10T09:00:00Z",
    ends_at: str = "2026-09-10T12:00:00Z",
    subtest: str = Subtest.MATH,
    requested_seats: int = 5,
    seat_capacity: int = 20,
    turnaround_buffer_minutes: Optional[int] = None,
    daily_hour_cap: Optional[float] = None,
    decision: str = CenterDecision.GRANT_FULL,
    session_overrides: Optional[JsonDict] = None,
) -> JsonDict:
    """A centre, room, certified proctor and one SCHEDULED sitting.

    Returns the dictionary from :func:`setup_center_with_room_and_proctor` plus
    ``{"session", "session_id"}``.
    """
    venue = setup_center_with_room_and_proctor(
        decision=decision,
        seat_capacity=seat_capacity,
        turnaround_buffer_minutes=turnaround_buffer_minutes,
        daily_hour_cap=daily_hour_cap,
    )
    session = create_session(
        venue["center_id"],
        venue["room_id"],
        starts_at,
        ends_at,
        subtest=subtest,
        requested_seats=requested_seats,
        **(session_overrides or {}),
    )
    session = assign_session_proctor(venue["center_id"], session["id"], venue["proctor_id"])
    venue.update({"session": session, "session_id": session["id"]})
    return venue


# ---------------------------------------------------------------------------
# Registration and exam day
# ---------------------------------------------------------------------------


def register_candidate(
    student_id: str,
    session_id: str,
    accommodation_request_id: Optional[str] = None,
    expected_exam_session_version: Optional[int] = None,
    headers: Optional[Dict[str, str]] = None,
) -> JsonDict:
    version = (
        expected_exam_session_version
        if expected_exam_session_version is not None
        else current_exam_session_version(session_id)
    )
    payload = factories.create_exam_registration_payload(student_id, session_id, version)
    if accommodation_request_id is not None:
        payload["accommodation_request_id"] = accommodation_request_id
    response = api_client.create_exam_registration(
        payload, headers=headers or make_registrar_headers()
    )
    return validate_success(response, expected_status=201)


def verify_candidate_identity(
    registration_id: str,
    proctor_id: str,
    decision: str = IdentityDecision.VERIFIED,
    identity_document_type: Optional[str] = "STATE_ID",
) -> JsonDict:
    response = api_client.verify_identity(
        registration_id,
        factories.identity_verification_payload(
            decision, identity_document_type=identity_document_type
        ),
        headers=make_proctor_headers(proctor_id),
    )
    return validate_success(response)


def check_in_candidate(registration_id: str, proctor_id: str) -> JsonDict:
    response = api_client.check_in(registration_id, headers=make_proctor_headers(proctor_id))
    return validate_success(response)


def record_candidate_result(registration_id: str, proctor_id: str, scale_score: int) -> JsonDict:
    response = api_client.record_result(
        registration_id,
        factories.record_result_payload(scale_score),
        headers=make_proctor_headers(proctor_id),
    )
    return validate_success(response)


def read_registration(
    registration_id: str, headers: Optional[Dict[str, str]] = None
) -> JsonDict:
    response = api_client.get_exam_registration(
        registration_id, headers=headers or make_state_authority_headers()
    )
    return validate_success(response)


def seat_and_score_candidate(
    registration_id: str,
    proctor_id: str,
    session_starts_at: str,
    scale_score: int = 150,
) -> JsonDict:
    """Verify identity, check in inside the seating window and record a result."""
    verify_candidate_identity(registration_id, proctor_id)
    ensure_clock(session_starts_at)
    check_in_candidate(registration_id, proctor_id)
    return record_candidate_result(registration_id, proctor_id, scale_score)


def setup_registered_candidate(
    starts_at: str = "2026-09-10T09:00:00Z",
    ends_at: str = "2026-09-10T12:00:00Z",
    subtest: str = Subtest.MATH,
    self_pay_authorized: bool = True,
    voucher_cents: int = 0,
    scale_score: int = 205,
    requested_seats: int = 5,
    seat_capacity: int = 20,
    **venue_overrides: Any,
) -> JsonDict:
    """A placed learner holding a REGISTERED seat on a SCHEDULED sitting.

    Returns the venue dictionary plus ``{"student_id", "registration",
    "registration_id", "starts_at", "ends_at"}``.
    """
    placed = create_placed_student(
        scale_score=scale_score, self_pay_authorized=self_pay_authorized
    )
    if voucher_cents:
        grant_voucher(placed["student_id"], voucher_cents)
    venue = setup_scheduled_session(
        starts_at=starts_at,
        ends_at=ends_at,
        subtest=subtest,
        requested_seats=requested_seats,
        seat_capacity=seat_capacity,
        **venue_overrides,
    )
    registration = register_candidate(placed["student_id"], venue["session_id"])
    venue.update(
        {
            "student_id": placed["student_id"],
            "student_headers": make_student_headers(placed["student_id"]),
            "registration": registration,
            "registration_id": registration["id"],
            "starts_at": starts_at,
            "ends_at": ends_at,
        }
    )
    return venue


def setup_checked_in_candidate(**overrides: Any) -> JsonDict:
    """A candidate verified and seated inside the seating window."""
    context = setup_registered_candidate(**overrides)
    verify_candidate_identity(context["registration_id"], context["proctor_id"])
    ensure_clock(context["starts_at"])
    context["registration"] = check_in_candidate(
        context["registration_id"], context["proctor_id"]
    )
    return context


def setup_scored_candidate(scale_score: int = 150, **overrides: Any) -> JsonDict:
    """A candidate whose subtest result has been recorded."""
    context = setup_checked_in_candidate(**overrides)
    context["registration"] = record_candidate_result(
        context["registration_id"], context["proctor_id"], scale_score
    )
    return context


# ---------------------------------------------------------------------------
# Accommodations
# ---------------------------------------------------------------------------


def create_accommodation(
    student_id: str,
    requested_format: str = TestFormat.EXTRA_TIME,
    documentation_ref: str = "DOC-A",
    headers: Optional[Dict[str, str]] = None,
) -> JsonDict:
    response = api_client.create_accommodation_request(
        factories.create_accommodation_request_payload(
            student_id, requested_format=requested_format, documentation_ref=documentation_ref
        ),
        headers=headers or make_registrar_headers(),
    )
    return validate_success(response, expected_status=201)


def request_accommodation_info(
    center_id: str, request_id: str, decision_note: str = "Supply a current evaluation"
) -> JsonDict:
    response = api_client.request_accommodation_info(
        request_id,
        factories.accommodation_info_request_payload(decision_note),
        headers=make_center_administrator_headers(center_id),
    )
    return validate_success(response)


def resubmit_accommodation(
    request_id: str, documentation_ref: str = "DOC-B", headers: Optional[Dict[str, str]] = None
) -> JsonDict:
    response = api_client.resubmit_accommodation(
        request_id,
        factories.accommodation_resubmission_payload(documentation_ref),
        headers=headers or make_registrar_headers(),
    )
    return validate_success(response)


def decide_accommodation(
    center_id: str,
    request_id: str,
    decision: str = AccommodationDecision.APPROVE,
    granted_format: Optional[str] = TestFormat.EXTRA_TIME,
    valid_until: Optional[str] = "2027-01-01T00:00:00Z",
) -> JsonDict:
    response = api_client.decide_accommodation(
        request_id,
        factories.accommodation_decision_payload(
            decision, granted_format=granted_format, valid_until=valid_until
        ),
        headers=make_center_administrator_headers(center_id),
    )
    return validate_success(response)


def setup_approved_accommodation(
    center_id: str,
    student_id: str,
    requested_format: str = TestFormat.BRAILLE,
    granted_format: Optional[str] = None,
    valid_until: str = "2027-01-01T00:00:00Z",
) -> JsonDict:
    """An APPROVED accommodation for one learner at one centre."""
    request = create_accommodation(student_id, requested_format=requested_format)
    return decide_accommodation(
        center_id,
        request["id"],
        AccommodationDecision.APPROVE,
        granted_format=granted_format or requested_format,
        valid_until=valid_until,
    )


# ---------------------------------------------------------------------------
# Credentials and transcripts
# ---------------------------------------------------------------------------

#: Four two-hour sittings on one calendar day, spaced by the default 45-minute
#: room turnaround so that all four fit in the same room.
FOUR_SUBTEST_SLOTS: Sequence[tuple] = (
    (Subtest.MATH, 8, 0, 10, 0),
    (Subtest.RLA, 10, 45, 12, 45),
    (Subtest.SCIENCE, 13, 30, 15, 30),
    (Subtest.SOCIAL_STUDIES, 16, 15, 18, 15),
)


def setup_four_subtest_results(
    exam_date: str = "2026-09-03",
    scale_scores: Optional[Dict[str, int]] = None,
    student_id: Optional[str] = None,
    venue: Optional[JsonDict] = None,
) -> JsonDict:
    """Score one learner on all four subtests in a single day.

    Returns ``{"venue", "student_id", "registrations", "exam_date"}`` where
    ``registrations`` maps each subtest onto its SCORED registration.
    """
    scores = dict(scale_scores or {subtest: 150 for subtest in Subtest.ALL})
    if venue is None:
        venue = setup_center_with_room_and_proctor(daily_hour_cap=12.00)
    if student_id is None:
        placed = create_placed_student(self_pay_authorized=True)
        student_id = placed["student_id"]

    ensure_clock(at(exam_date, 0))
    sessions = {}
    for subtest, start_hour, start_minute, end_hour, end_minute in FOUR_SUBTEST_SLOTS:
        session = create_session(
            venue["center_id"],
            venue["room_id"],
            at(exam_date, start_hour, start_minute),
            at(exam_date, end_hour, end_minute),
            subtest=subtest,
            requested_seats=5,
        )
        session = assign_session_proctor(
            venue["center_id"], session["id"], venue["proctor_id"]
        )
        sessions[subtest] = session

    registrations = {}
    for subtest, session in sessions.items():
        registrations[subtest] = register_candidate(student_id, session["id"])

    for subtest, _start_hour, _start_minute, _end_hour, _end_minute in FOUR_SUBTEST_SLOTS:
        session = sessions[subtest]
        registrations[subtest] = seat_and_score_candidate(
            registrations[subtest]["id"],
            venue["proctor_id"],
            session["starts_at"],
            scale_score=scores[subtest],
        )

    return {
        "venue": venue,
        "student_id": student_id,
        "sessions": sessions,
        "registrations": registrations,
        "exam_date": exam_date,
    }


def issue_credential(student_id: str) -> JsonDict:
    response = api_client.issue_credential(
        factories.create_credential_issuance_payload(student_id),
        headers=make_state_authority_headers(),
    )
    return validate_success(response, expected_status=201)


def setup_issued_credential(
    exam_date: str = "2026-09-03",
    scale_scores: Optional[Dict[str, int]] = None,
    student_id: Optional[str] = None,
    venue: Optional[JsonDict] = None,
) -> JsonDict:
    """A learner holding an ISSUED HSE credential.

    Returns the dictionary from :func:`setup_four_subtest_results` plus
    ``{"credential", "credential_id"}``.
    """
    context = setup_four_subtest_results(
        exam_date=exam_date, scale_scores=scale_scores, student_id=student_id, venue=venue
    )
    credential = issue_credential(context["student_id"])
    context.update({"credential": credential, "credential_id": credential["id"]})
    return context


def create_transcript_order(
    student_id: str,
    credential_issuance_id: str,
    copies: int = 1,
    delivery: str = TranscriptDelivery.STANDARD,
    destination_type: str = TranscriptDestination.SELF,
    headers: Optional[Dict[str, str]] = None,
) -> JsonDict:
    response = api_client.create_transcript_order(
        student_id,
        factories.create_transcript_order_payload(
            credential_issuance_id,
            copies=copies,
            delivery=delivery,
            destination_type=destination_type,
        ),
        headers=headers or make_registrar_headers(),
    )
    return validate_success(response, expected_status=201)


def fulfill_transcript_order(order_id: str) -> JsonDict:
    response = api_client.fulfill_transcript_order(order_id, headers=make_registrar_headers())
    return validate_success(response)


# ---------------------------------------------------------------------------
# Performance reporting and funding
# ---------------------------------------------------------------------------


def create_funding_period(**overrides: Any) -> JsonDict:
    response = api_client.create_funding_period(
        factories.create_funding_period_payload(**overrides),
        headers=make_state_authority_headers(),
    )
    return validate_success(response, expected_status=201)


def read_funding_period(period_id: str, headers: Optional[Dict[str, str]] = None) -> JsonDict:
    response = api_client.get_funding_period(
        period_id, headers=headers or make_state_authority_headers()
    )
    return validate_success(response)


def record_outcome(
    student_id: str,
    funding_period_id: str,
    measure_type: str = MeasureType.EMPLOYMENT_Q2,
    evidence_ref: str = "NRS-0001",
    credential_issuance_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> JsonDict:
    payload = factories.create_outcome_record_payload(
        student_id, funding_period_id, measure_type=measure_type, evidence_ref=evidence_ref
    )
    if credential_issuance_id is not None:
        payload["credential_issuance_id"] = credential_issuance_id
    response = api_client.create_outcome_record(
        payload, headers=headers or make_program_coordinator_headers()
    )
    return validate_success(response, expected_status=201)


def decide_outcome(
    outcome_id: str,
    decision: str = OutcomeDecision.CERTIFY,
    headers: Optional[Dict[str, str]] = None,
) -> JsonDict:
    response = api_client.decide_outcome_certification(
        outcome_id,
        factories.outcome_certification_payload(decision),
        headers=headers or make_state_authority_headers(),
    )
    return validate_success(response)


def read_outcome(outcome_id: str, headers: Optional[Dict[str, str]] = None) -> JsonDict:
    response = api_client.get_outcome_record(
        outcome_id, headers=headers or make_state_authority_headers()
    )
    return validate_success(response)


def certified_outcome(
    student_id: str,
    funding_period_id: str,
    measure_type: str = MeasureType.EMPLOYMENT_Q2,
    evidence_ref: str = "NRS-0001",
    credential_issuance_id: Optional[str] = None,
) -> JsonDict:
    """A claim recorded by the coordinator and certified by the state authority."""
    outcome = record_outcome(
        student_id,
        funding_period_id,
        measure_type=measure_type,
        evidence_ref=evidence_ref,
        credential_issuance_id=credential_issuance_id,
        headers=make_program_coordinator_headers(),
    )
    return decide_outcome(
        outcome["id"], OutcomeDecision.CERTIFY, headers=make_state_authority_headers()
    )


def run_allocation(
    period_id: str,
    variant: str = AllocationVariant.FINAL,
    expected_funding_period_version: Optional[int] = None,
) -> JsonDict:
    version = (
        expected_funding_period_version
        if expected_funding_period_version is not None
        else current_funding_period_version(period_id)
    )
    response = api_client.run_allocation(
        period_id,
        factories.allocation_run_payload(version, variant=variant),
        headers=make_state_authority_headers(),
    )
    return validate_success(response)


def read_allocation_preview(
    period_id: str,
    variant: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> JsonDict:
    params = {"variant": variant} if variant is not None else None
    response = api_client.get_allocation_preview(
        period_id, headers=headers or make_state_authority_headers(), params=params
    )
    return validate_success(response)


def close_funding_period(period_id: str) -> JsonDict:
    response = api_client.close_funding_period(
        period_id, headers=make_state_authority_headers()
    )
    return validate_success(response)


def setup_committed_funding(
    rate_cents_per_weight: int = 10000,
    total_cents: int = 100000,
    measure_type: str = MeasureType.EMPLOYMENT_Q2,
) -> JsonDict:
    """An OPEN period with one CERTIFIED, COMMITTED claim allocated under FINAL.

    Returns ``{"period", "period_id", "student_id", "outcome", "outcome_id"}``.
    """
    period = create_funding_period(
        rate_cents_per_weight=rate_cents_per_weight, total_cents=total_cents
    )
    placed = create_placed_student()
    outcome = certified_outcome(placed["student_id"], period["id"], measure_type=measure_type)
    run_allocation(period["id"], AllocationVariant.FINAL)
    return {
        "period": read_funding_period(period["id"]),
        "period_id": period["id"],
        "student_id": placed["student_id"],
        "outcome": read_outcome(outcome["id"]),
        "outcome_id": outcome["id"],
    }


# ---------------------------------------------------------------------------
# Listing helpers
# ---------------------------------------------------------------------------


def list_all(list_method, headers: Dict[str, str], **params: Any) -> List[JsonDict]:
    """Read one page of a collection and return just the items."""
    response = list_method(headers=headers, params=params or None)
    data = get_success_data(response)
    return data if isinstance(data, list) else data["items"]


# ---------------------------------------------------------------------------
# Single-record readers
# ---------------------------------------------------------------------------


def read_class_section(section_id: str, headers: Optional[Dict[str, str]] = None) -> JsonDict:
    response = api_client.get_class_section(
        section_id, headers=headers or make_program_coordinator_headers()
    )
    return validate_success(response)


def read_enrollment(enrollment_id: str, headers: Optional[Dict[str, str]] = None) -> JsonDict:
    response = api_client.get_enrollment(
        enrollment_id, headers=headers or make_program_coordinator_headers()
    )
    return validate_success(response)


def read_attendance_entry(entry_id: str, headers: Optional[Dict[str, str]] = None) -> JsonDict:
    response = api_client.get_attendance_entry(
        entry_id, headers=headers or make_program_coordinator_headers()
    )
    return validate_success(response)


def read_test_event(test_event_id: str, headers: Optional[Dict[str, str]] = None) -> JsonDict:
    response = api_client.get_test_event(
        test_event_id, headers=headers or make_program_coordinator_headers()
    )
    return validate_success(response)


def read_testing_center(center_id: str, headers: Optional[Dict[str, str]] = None) -> JsonDict:
    response = api_client.get_testing_center(
        center_id, headers=headers or make_state_authority_headers()
    )
    return validate_success(response)


def read_testing_room(room_id: str, headers: Optional[Dict[str, str]] = None) -> JsonDict:
    response = api_client.get_testing_room(
        room_id, headers=headers or make_state_authority_headers()
    )
    return validate_success(response)


def read_proctor(proctor_id: str, headers: Optional[Dict[str, str]] = None) -> JsonDict:
    response = api_client.get_proctor(
        proctor_id, headers=headers or make_state_authority_headers()
    )
    return validate_success(response)


def read_accommodation(request_id: str, headers: Optional[Dict[str, str]] = None) -> JsonDict:
    response = api_client.get_accommodation_request(
        request_id, headers=headers or make_registrar_headers()
    )
    return validate_success(response)


def read_credential(credential_id: str, headers: Optional[Dict[str, str]] = None) -> JsonDict:
    response = api_client.get_credential(
        credential_id, headers=headers or make_state_authority_headers()
    )
    return validate_success(response)


def read_transcript_order(order_id: str, headers: Optional[Dict[str, str]] = None) -> JsonDict:
    # PRD authorises ProgramCoordinator, StateAuthority and Student on the single-order
    # read; a Registrar may create and fulfil an order but may not read one back.
    response = api_client.get_transcript_order(
        order_id, headers=headers or make_program_coordinator_headers()
    )
    return validate_success(response)
