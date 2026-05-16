"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body (PRD §3 narrative + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed fields are intentionally omitted so the
implementation cannot accidentally accept them as inputs.

PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
PRD §2.8: monetary fields are integer cents.
"""
from __future__ import annotations

import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Timestamp helpers — PRD §2.4 format with three fractional digits.
# ---------------------------------------------------------------------------
def iso_utc(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def iso_now() -> str:
    return iso_utc(utcnow())


def iso_offset(*, days: int = 0, hours: int = 0, minutes: int = 0,
               seconds: int = 0,
               base: Optional[datetime] = None) -> str:
    base = base or utcnow()
    return iso_utc(base + timedelta(
        days=days, hours=hours, minutes=minutes, seconds=seconds,
    ))


def parse_iso(iso_ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp produced by iso_utc back into a
    timezone-aware datetime."""
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


_ALPHANUM = string.ascii_uppercase + string.digits


def random_suffix(n: int = 8) -> str:
    return "".join(random.choices(_ALPHANUM, k=n))


def random_email(prefix: str = "user") -> str:
    return f"{prefix}_{random_suffix(8).lower()}@test.example"


# ---------------------------------------------------------------------------
# Tutor — PRD §3.1
# ---------------------------------------------------------------------------
def create_tutor_payload(
    *,
    display_name: Optional[str] = None,
    email: Optional[str] = None,
    hourly_rate_cents: int = TEST_DEFAULTS["HOURLY_RATE_CENTS"],
    trial_rate_cents: int = TEST_DEFAULTS["TRIAL_RATE_CENTS"],
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /tutoring/tutors — Tutor or PlatformAdmin.

    PRD §3.1: required input fields are display_name, email,
    hourly_rate_cents, trial_rate_cents.
    """
    payload: Dict[str, Any] = {
        "display_name": (
            display_name if display_name is not None
            else f"Tutor {random_suffix(4)}"
        ),
        "email": email or random_email("tutor"),
        "hourly_rate_cents": hourly_rate_cents,
        "trial_rate_cents": trial_rate_cents,
    }
    payload.update(overrides)
    return payload


def patch_tutor_payload(
    *,
    display_name: Optional[str] = None,
    hourly_rate_cents: Optional[int] = None,
    trial_rate_cents: Optional[int] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PATCH /tutoring/tutors/{id} — Tutor or PlatformAdmin.

    PRD §2.7 + §3.1: optional display_name, hourly_rate_cents,
    trial_rate_cents, and `version` for optimistic locking. Omitting
    `version` skips OCC; supplying a stale value yields
    ERR_VERSION_CONFLICT.
    """
    payload: Dict[str, Any] = {}
    if display_name is not None:
        payload["display_name"] = display_name
    if hourly_rate_cents is not None:
        payload["hourly_rate_cents"] = hourly_rate_cents
    if trial_rate_cents is not None:
        payload["trial_rate_cents"] = trial_rate_cents
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Credential — PRD §3.1
# ---------------------------------------------------------------------------
def submit_credential_payload(
    *,
    credential_type: str = "GOVERNMENT_ID",
    document_ref: Optional[str] = None,
    expires_at: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /tutoring/tutors/{id}/credentials — Tutor only.

    PRD §3.1: input fields are credential_type (GOVERNMENT_ID, DEGREE,
    TEACHING_LICENSE, BACKGROUND_CHECK), document_ref, optional
    expires_at (null means no expiry).
    """
    payload: Dict[str, Any] = {
        "credential_type": credential_type,
        "document_ref": document_ref or f"doc_{random_suffix(8)}",
        "expires_at": expires_at,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# SubjectTag — PRD §3.2
# ---------------------------------------------------------------------------
def propose_subject_payload(
    *,
    subject_code: str = TEST_DEFAULTS["DEFAULT_SUBJECT"],
    proficiency_level: str = TEST_DEFAULTS["DEFAULT_PROFICIENCY"],
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /tutoring/tutors/{id}/subjects — Tutor only.

    PRD §3.2: required input fields are subject_code (uppercase letter
    then 2-29 chars from uppercase letters, digits, underscores; total
    3-30 chars), proficiency_level (BEGINNER, INTERMEDIATE, ADVANCED,
    EXPERT).
    """
    payload: Dict[str, Any] = {
        "subject_code": subject_code,
        "proficiency_level": proficiency_level,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Student — PRD §3.3
# ---------------------------------------------------------------------------
def create_student_payload(
    *,
    display_name: Optional[str] = None,
    email: Optional[str] = None,
    account_type: str = "ADULT",
    parent_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /tutoring/students — Student, Parent, or PlatformAdmin.

    PRD §3.3: required input fields are display_name, email,
    account_type (ADULT or MINOR), optional parent_id (null for ADULT,
    must be set for MINOR).
    """
    payload: Dict[str, Any] = {
        "display_name": (
            display_name if display_name is not None
            else f"Student {random_suffix(4)}"
        ),
        "email": email or random_email("student"),
        "account_type": account_type,
        "parent_id": parent_id,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Parent — PRD §3.3
# ---------------------------------------------------------------------------
def create_parent_payload(
    *,
    display_name: Optional[str] = None,
    email: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /tutoring/parents — Parent or PlatformAdmin.

    PRD §3.3: required input fields are display_name, email.
    """
    payload: Dict[str, Any] = {
        "display_name": (
            display_name if display_name is not None
            else f"Parent {random_suffix(4)}"
        ),
        "email": email or random_email("parent"),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Session — PRD §3.4
# ---------------------------------------------------------------------------
def book_session_payload(
    *,
    tutor_id: str,
    student_id: str,
    subject_code: str = TEST_DEFAULTS["DEFAULT_SUBJECT"],
    start_at: Optional[str] = None,
    end_at: Optional[str] = None,
    is_trial: bool = False,
    apply_credits: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /tutoring/sessions — Student or Parent.

    PRD §3.4: required input fields are tutor_id, student_id,
    subject_code, start_at, end_at; optional is_trial (default false),
    apply_credits (default false).
    """
    if start_at is None:
        start_at = iso_offset(hours=2)
    if end_at is None:
        # Default to a 60-minute window relative to start_at.
        end_at = iso_utc(parse_iso(start_at) + timedelta(minutes=60))
    payload: Dict[str, Any] = {
        "tutor_id": tutor_id,
        "student_id": student_id,
        "subject_code": subject_code,
        "start_at": start_at,
        "end_at": end_at,
        "is_trial": is_trial,
        "apply_credits": apply_credits,
    }
    payload.update(overrides)
    return payload


def complete_session_payload(
    *,
    adjusted_minutes: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /tutoring/sessions/{id}/complete — Tutor only.

    PRD §3.5: optional adjusted_minutes (defaults to scheduled minutes
    if omitted; must lie in [0, scheduled_minutes]).
    """
    payload: Dict[str, Any] = {}
    if adjusted_minutes is not None:
        payload["adjusted_minutes"] = adjusted_minutes
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# RefundDispute — PRD §3.7
# ---------------------------------------------------------------------------
def open_dispute_payload(
    *,
    session_id: str,
    reason_code: str = "QUALITY_ISSUE",
    requested_amount_cents: int = 1000,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /tutoring/disputes — Student or Parent.

    PRD §3.7: required input fields are session_id, reason_code
    (TUTOR_NO_SHOW, QUALITY_ISSUE, TECHNICAL_FAILURE, OTHER),
    requested_amount_cents. (opened_by_role and opened_by_user_id are
    server-derived from the X-User-Role / X-User-ID headers.)
    """
    payload: Dict[str, Any] = {
        "session_id": session_id,
        "reason_code": reason_code,
        "requested_amount_cents": requested_amount_cents,
    }
    payload.update(overrides)
    return payload


def counter_dispute_payload(
    *,
    counter_amount_cents: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /tutoring/disputes/{id}/counter — Tutor only.

    PRD §3.7: required input field is counter_amount_cents (must lie in
    [0, requested_amount_cents]).
    """
    payload: Dict[str, Any] = {"counter_amount_cents": counter_amount_cents}
    payload.update(overrides)
    return payload


def arbitrate_dispute_payload(
    *,
    decision: str,
    refund_amount_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /tutoring/disputes/{id}/arbitrate — PlatformArbiter only.

    PRD §3.7: required input field is decision (REFUND or DENY);
    optional refund_amount_cents when decision is REFUND.
    """
    payload: Dict[str, Any] = {"decision": decision}
    if refund_amount_cents is not None:
        payload["refund_amount_cents"] = refund_amount_cents
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# PayoutBatch — PRD §3.6
# ---------------------------------------------------------------------------
def create_payout_payload(
    *,
    tutor_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /tutoring/payouts — PlatformAdmin only.

    PRD §3.6: required input field is tutor_id.
    """
    payload: Dict[str, Any] = {"tutor_id": tutor_id}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock advance — PRD §3.9
# ---------------------------------------------------------------------------
def clock_advance_payload(
    *,
    to_iso8601: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /tutoring/_clock/advance — PlatformAdmin only.

    PRD §3.9: required input field is to_iso8601 (ISO 8601 UTC instant).
    """
    payload: Dict[str, Any] = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


__all__ = [
    "iso_utc",
    "utcnow",
    "iso_now",
    "iso_offset",
    "parse_iso",
    "random_suffix",
    "random_email",
    "create_tutor_payload",
    "patch_tutor_payload",
    "submit_credential_payload",
    "propose_subject_payload",
    "create_student_payload",
    "create_parent_payload",
    "book_session_payload",
    "complete_session_payload",
    "open_dispute_payload",
    "counter_dispute_payload",
    "arbitrate_dispute_payload",
    "create_payout_payload",
    "clock_advance_payload",
]
