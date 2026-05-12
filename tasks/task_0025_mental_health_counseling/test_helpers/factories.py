"""Payload factories for the Mental Health Counseling Platform.

One factory per entity. Field names match the PRD verbatim. All factories
accept **overrides so tests can pin the values they need to exercise
boundary or precondition behaviour.

Per PRD §3.1, §3.3, §3.4, §3.6, §3.7, §3.10 — only `source: input` fields
appear here. Computed fields (status, refund_state, package_balance_sessions,
etc.) are NEVER included in input payloads.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Unique-input helpers
# ---------------------------------------------------------------------------
def unique_email(local_prefix: str = "user") -> str:
    return f"{local_prefix}-{uuid.uuid4().hex[:10]}@example.test".lower()


def unique_license_number(prefix: str = "LIC") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def unique_full_name(prefix: str = "Person") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


# ---------------------------------------------------------------------------
# Counselor (PRD §3.1)
# ---------------------------------------------------------------------------
def create_counselor_payload(
    *,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    license_number: Optional[str] = None,
    license_expires_at: str = "2099-12-31T00:00:00.000Z",
    specialty_tags: Optional[List[str]] = None,
    supported_channels: Optional[List[str]] = None,
    timezone: str = "America/Los_Angeles",
    revenue_share_bps: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name or unique_full_name("Counselor"),
        "email": email or unique_email("counselor"),
        "license_number": license_number or unique_license_number(),
        "license_expires_at": license_expires_at,
        "specialty_tags": list(specialty_tags) if specialty_tags is not None
            else ["ANXIETY", "DEPRESSION"],
        "supported_channels": list(supported_channels) if supported_channels is not None
            else ["VIDEO", "AUDIO", "TEXT"],
        "timezone": timezone,
    }
    if revenue_share_bps is not None:
        payload["revenue_share_bps"] = revenue_share_bps
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Client (PRD §3.3)
# ---------------------------------------------------------------------------
def create_client_payload(
    *,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    timezone: str = "America/Los_Angeles",
    emergency_contact_name: str = "Emergency Contact",
    emergency_contact_phone: str = "+15551230000",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name or unique_full_name("Client"),
        "email": email or unique_email("client"),
        "timezone": timezone,
        "emergency_contact_name": emergency_contact_name,
        "emergency_contact_phone": emergency_contact_phone,
    }
    payload.update(overrides)
    return payload


def credit_package_payload(
    *,
    sessions: int = 5,
    version: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"sessions": sessions, "version": version}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Availability slot (PRD §3.4)
# ---------------------------------------------------------------------------
def create_availability_slot_payload(
    *,
    counselor_id: str,
    start_at: str,
    end_at: str,
    channel: str = "VIDEO",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "counselor_id": counselor_id,
        "start_at": start_at,
        "end_at": end_at,
        "channel": channel,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Appointment (PRD §3.4)
# ---------------------------------------------------------------------------
def create_appointment_payload(
    *,
    counselor_id: str,
    client_id: str,
    slot_id: str,
    appointment_type: str = "STANDARD",
    payment_mode: str = "PAY_PER_SESSION",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "counselor_id": counselor_id,
        "client_id": client_id,
        "slot_id": slot_id,
        "appointment_type": appointment_type,
        "payment_mode": payment_mode,
    }
    payload.update(overrides)
    return payload


def cancel_appointment_payload(
    *, reason: Optional[str] = "CLIENT_CANCEL", **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


def reschedule_appointment_payload(
    *, new_slot_id: str, **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"new_slot_id": new_slot_id}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Counseling record (PRD §3.6)
# ---------------------------------------------------------------------------
def create_counseling_record_payload(
    *,
    appointment_id: str,
    encrypted_note_blob: str = "Y2lwaGVydGV4dC1ibG9iLWFiYw==",
    crisis_acknowledged: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "appointment_id": appointment_id,
        "encrypted_note_blob": encrypted_note_blob,
    }
    if crisis_acknowledged is not None:
        payload["crisis_acknowledged"] = crisis_acknowledged
    payload.update(overrides)
    return payload


def export_counseling_record_payload(
    *, export_consent: bool = True, **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"export_consent": export_consent}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Crisis incident (PRD §3.7)
# ---------------------------------------------------------------------------
def create_crisis_incident_payload(
    *,
    appointment_id: str,
    detection_source: str = "COUNSELOR_TRIGGERED",
    trigger_keyword: Optional[str] = None,
    severity: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "appointment_id": appointment_id,
        "detection_source": detection_source,
    }
    if trigger_keyword is not None:
        payload["trigger_keyword"] = trigger_keyword
    if severity is not None:
        payload["severity"] = severity
    payload.update(overrides)
    return payload


def crisis_handover_payload(
    *, severity: str = "MEDIUM", **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"severity": severity}
    payload.update(overrides)
    return payload


def schedule_follow_up_payload(
    *, follow_up_due_at: Optional[str] = None, **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if follow_up_due_at is not None:
        payload["follow_up_due_at"] = follow_up_due_at
    payload.update(overrides)
    return payload


def resolve_crisis_payload(
    *, follow_up_completed_at: str, **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"follow_up_completed_at": follow_up_completed_at}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Supervision & CE (PRD §3.10)
# ---------------------------------------------------------------------------
def create_supervision_session_payload(
    *,
    counselor_id: str,
    supervisor_id: str,
    case_appointment_id: str,
    scheduled_at: str,
    duration_hours: float = 1.0,
    discussion_notes: str = "Routine supervision discussion.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "counselor_id": counselor_id,
        "supervisor_id": supervisor_id,
        "case_appointment_id": case_appointment_id,
        "scheduled_at": scheduled_at,
        "duration_hours": duration_hours,
        "discussion_notes": discussion_notes,
    }
    payload.update(overrides)
    return payload


def approve_supervision_payload(
    *, evaluation_score: int = 4, **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"evaluation_score": evaluation_score}
    payload.update(overrides)
    return payload


def create_ce_record_payload(
    *,
    counselor_id: str,
    course_title: str = "Continuing Education in Anxiety",
    completed_at: str = "2026-05-01T00:00:00.000Z",
    hours_claimed: float = 12.0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "counselor_id": counselor_id,
        "course_title": course_title,
        "completed_at": completed_at,
        "hours_claimed": hours_claimed,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Payouts (PRD §3.9)
# ---------------------------------------------------------------------------
def create_payout_payload(
    *,
    counselor_id: str,
    period_start_at: str,
    period_end_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "counselor_id": counselor_id,
        "period_start_at": period_start_at,
        "period_end_at": period_end_at,
    }
    payload.update(overrides)
    return payload


def reverse_payout_payload(
    *, reason: str = "Reversal requested", **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"reason": reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Disqualify counselor (PRD §3.2)
# ---------------------------------------------------------------------------
def disqualify_counselor_payload(
    *, reason: Optional[str] = "Test disqualification", **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Event emission (PRD §3.11)
# ---------------------------------------------------------------------------
def emit_event_payload(
    *, event_type: str = "im_sync", payload: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "event_type": event_type,
        "payload": payload if payload is not None else {},
    }
    body.update(overrides)
    return body
