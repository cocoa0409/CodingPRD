"""Request-payload builders.

Each ``create_*_payload`` carries only the client-supplied input fields the PRD
declares required for that endpoint; optional fields are left out so that
default-value behaviour stays observable. Pass keyword overrides to add an
optional field or to replace a required one.
"""

from __future__ import annotations

import itertools
from typing import Any, Dict, List, Optional

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

_counter = itertools.count(1)


def unique_suffix() -> str:
    """A short suffix that is unique within one test process."""
    return f"{next(_counter):04d}"


def _payload(base: JsonDict, overrides: JsonDict) -> JsonDict:
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Learners
# ---------------------------------------------------------------------------


def create_student_payload(**overrides: Any) -> JsonDict:
    suffix = unique_suffix()
    return _payload(
        {
            "full_name": f"Learner {suffix}",
            "email": f"learner{suffix}@example.test",
            "primary_track": ProgramTrack.HSE_PREP,
        },
        overrides,
    )


def voucher_adjustment_payload(delta_cents: int, **overrides: Any) -> JsonDict:
    return _payload({"delta_cents": delta_cents}, overrides)


# ---------------------------------------------------------------------------
# Testing centres, rooms and proctors
# ---------------------------------------------------------------------------


def create_testing_center_payload(**overrides: Any) -> JsonDict:
    return _payload(
        {"name": f"Riverside Testing Centre {unique_suffix()}", "state_code": "OR"}, overrides
    )


def center_authorization_decision_payload(
    decision: str = CenterDecision.GRANT_FULL, **overrides: Any
) -> JsonDict:
    return _payload({"decision": decision}, overrides)


def suspend_center_payload(
    suspended_reason: str = "State audit finding", **overrides: Any
) -> JsonDict:
    return _payload({"suspended_reason": suspended_reason}, overrides)


def create_testing_room_payload(**overrides: Any) -> JsonDict:
    return _payload({"room_code": f"R{unique_suffix()}", "seat_capacity": 20}, overrides)


def out_of_service_payload(
    service_note: str = "Ceiling repair scheduled", **overrides: Any
) -> JsonDict:
    return _payload({"service_note": service_note}, overrides)


def create_proctor_payload(**overrides: Any) -> JsonDict:
    return _payload({"full_name": f"Proctor {unique_suffix()}"}, overrides)


def proctor_certification_decision_payload(
    decision: str = ProctorDecision.CERTIFY,
    certification_expires_at: Optional[str] = "2027-06-30T00:00:00Z",
    **overrides: Any,
) -> JsonDict:
    payload: JsonDict = {"decision": decision}
    if certification_expires_at is not None:
        payload["certification_expires_at"] = certification_expires_at
    return _payload(payload, overrides)


# ---------------------------------------------------------------------------
# Sections, enrollment and attendance
# ---------------------------------------------------------------------------


def create_class_section_payload(**overrides: Any) -> JsonDict:
    return _payload(
        {
            "program_track": ProgramTrack.HSE_PREP,
            "title": f"HSE Evening {unique_suffix()}",
            "instructor_user_id": "instructor-1",
            "min_efl_level": 1,
            "max_efl_level": 6,
            "seats_total": 20,
            "weekly_hours": 6.00,
        },
        overrides,
    )


def section_transition_payload(target_status: str = SectionStatus.OPEN, **overrides: Any) -> JsonDict:
    return _payload({"target_status": target_status}, overrides)


def create_enrollment_payload(
    student_id: str, class_section_id: str, **overrides: Any
) -> JsonDict:
    return _payload({"student_id": student_id, "class_section_id": class_section_id}, overrides)


def withdraw_enrollment_payload(
    exit_reason: str = "Learner relocated", **overrides: Any
) -> JsonDict:
    return _payload({"exit_reason": exit_reason}, overrides)


def create_attendance_entry_payload(
    attendance_date: str, hours: float, **overrides: Any
) -> JsonDict:
    return _payload({"attendance_date": attendance_date, "hours": hours}, overrides)


def void_attendance_payload(
    expected_enrollment_version: int, void_reason: str = "Posted in error", **overrides: Any
) -> JsonDict:
    return _payload(
        {
            "void_reason": void_reason,
            "expected_enrollment_version": expected_enrollment_version,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Standardised test events
# ---------------------------------------------------------------------------


def create_test_event_payload(
    student_id: str,
    scheduled_for: str,
    purpose: str = TestEventPurpose.PRE_TEST,
    test_form: str = TestForm.CASAS_R_900,
    **overrides: Any,
) -> JsonDict:
    return _payload(
        {
            "student_id": student_id,
            "purpose": purpose,
            "test_form": test_form,
            "scheduled_for": scheduled_for,
        },
        overrides,
    )


def score_test_event_payload(scale_score: int, **overrides: Any) -> JsonDict:
    return _payload({"scale_score": scale_score}, overrides)


# ---------------------------------------------------------------------------
# Exam sittings
# ---------------------------------------------------------------------------


def create_exam_session_payload(
    testing_room_id: str,
    starts_at: str,
    ends_at: str,
    subtest: str = Subtest.MATH,
    requested_seats: int = 5,
    **overrides: Any,
) -> JsonDict:
    return _payload(
        {
            "testing_room_id": testing_room_id,
            "subtest": subtest,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "requested_seats": requested_seats,
        },
        overrides,
    )


def proctor_assignment_payload(proctor_id: str, **overrides: Any) -> JsonDict:
    return _payload({"proctor_id": proctor_id}, overrides)


def cancel_exam_session_payload(
    cancel_reason: str = "Centre closure", **overrides: Any
) -> JsonDict:
    return _payload({"cancel_reason": cancel_reason}, overrides)


# ---------------------------------------------------------------------------
# Registration and exam day
# ---------------------------------------------------------------------------


def create_exam_registration_payload(
    student_id: str,
    exam_session_id: str,
    expected_exam_session_version: int,
    **overrides: Any,
) -> JsonDict:
    return _payload(
        {
            "student_id": student_id,
            "exam_session_id": exam_session_id,
            "expected_exam_session_version": expected_exam_session_version,
        },
        overrides,
    )


def identity_verification_payload(
    decision: str = IdentityDecision.VERIFIED,
    identity_document_type: Optional[str] = "STATE_ID",
    **overrides: Any,
) -> JsonDict:
    payload: JsonDict = {"decision": decision}
    if identity_document_type is not None:
        payload["identity_document_type"] = identity_document_type
    return _payload(payload, overrides)


def record_result_payload(scale_score: int, **overrides: Any) -> JsonDict:
    return _payload({"scale_score": scale_score}, overrides)


# ---------------------------------------------------------------------------
# Accommodations
# ---------------------------------------------------------------------------


def create_accommodation_request_payload(
    student_id: str,
    requested_format: str = TestFormat.EXTRA_TIME,
    documentation_ref: str = "DOC-A",
    **overrides: Any,
) -> JsonDict:
    return _payload(
        {
            "student_id": student_id,
            "requested_format": requested_format,
            "documentation_ref": documentation_ref,
        },
        overrides,
    )


def accommodation_info_request_payload(
    decision_note: str = "Please supply a current evaluation", **overrides: Any
) -> JsonDict:
    return _payload({"decision_note": decision_note}, overrides)


def accommodation_resubmission_payload(
    documentation_ref: str = "DOC-B", **overrides: Any
) -> JsonDict:
    return _payload({"documentation_ref": documentation_ref}, overrides)


def accommodation_decision_payload(
    decision: str = AccommodationDecision.APPROVE,
    granted_format: Optional[str] = TestFormat.EXTRA_TIME,
    valid_until: Optional[str] = "2027-01-01T00:00:00Z",
    **overrides: Any,
) -> JsonDict:
    payload: JsonDict = {"decision": decision}
    if decision == AccommodationDecision.APPROVE:
        if granted_format is not None:
            payload["granted_format"] = granted_format
        if valid_until is not None:
            payload["valid_until"] = valid_until
    return _payload(payload, overrides)


# ---------------------------------------------------------------------------
# Credentials and transcripts
# ---------------------------------------------------------------------------


def create_credential_issuance_payload(student_id: str, **overrides: Any) -> JsonDict:
    return _payload({"student_id": student_id}, overrides)


def create_transcript_order_payload(
    credential_issuance_id: str,
    copies: int = 1,
    delivery: str = TranscriptDelivery.STANDARD,
    destination_type: str = TranscriptDestination.SELF,
    **overrides: Any,
) -> JsonDict:
    return _payload(
        {
            "credential_issuance_id": credential_issuance_id,
            "copies": copies,
            "delivery": delivery,
            "destination_type": destination_type,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Performance reporting and funding
# ---------------------------------------------------------------------------


def create_outcome_record_payload(
    student_id: str,
    funding_period_id: str,
    measure_type: str = MeasureType.EMPLOYMENT_Q2,
    evidence_ref: str = "NRS-0001",
    **overrides: Any,
) -> JsonDict:
    return _payload(
        {
            "student_id": student_id,
            "funding_period_id": funding_period_id,
            "measure_type": measure_type,
            "evidence_ref": evidence_ref,
        },
        overrides,
    )


def outcome_certification_payload(
    decision: str = OutcomeDecision.CERTIFY, **overrides: Any
) -> JsonDict:
    return _payload({"decision": decision}, overrides)


def create_funding_period_payload(
    rate_cents_per_weight: int = 10000,
    total_cents: int = 100000,
    start_date: str = "2026-08-01",
    end_date: str = "2026-12-31",
    **overrides: Any,
) -> JsonDict:
    return _payload(
        {
            "label": f"PY2026-{unique_suffix()}",
            "start_date": start_date,
            "end_date": end_date,
            "rate_cents_per_weight": rate_cents_per_weight,
            "total_cents": total_cents,
        },
        overrides,
    )


def allocation_run_payload(
    expected_funding_period_version: int,
    variant: str = AllocationVariant.FINAL,
    **overrides: Any,
) -> JsonDict:
    return _payload(
        {
            "variant": variant,
            "expected_funding_period_version": expected_funding_period_version,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------


def clock_payload(current_utc: str, **overrides: Any) -> JsonDict:
    return _payload({"current_utc": current_utc}, overrides)


# ---------------------------------------------------------------------------
# Miscellaneous
# ---------------------------------------------------------------------------


def supported_formats(*formats: str) -> List[str]:
    return list(formats)
