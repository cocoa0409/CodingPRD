"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body (PRD §3 narrative + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed and system-source fields are intentionally
omitted so the implementation cannot accidentally accept them as inputs.

PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
PRD §2.7: monetary fields are integer cents.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional


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


_ALPHANUM = string.ascii_uppercase + string.digits


def random_suffix(n: int = 8) -> str:
    return "".join(random.choices(_ALPHANUM, k=n))


# ---------------------------------------------------------------------------
# Program — PRD §3.1
# ---------------------------------------------------------------------------
def create_program_payload(
    *,
    institution_name: Optional[str] = None,
    sport: str = "FOOTBALL",
    division: str = "DI",
    scholarship_cap_equivalencies: float = 85.0,
    roster_cap_count: int = 85,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /programs — ComplianceOfficer only.

    PRD §3.1: required input fields are institution_name, sport, division,
    scholarship_cap_equivalencies, roster_cap_count.
    """
    payload: Dict[str, Any] = {
        "institution_name": (
            institution_name if institution_name is not None
            else f"University {random_suffix(4)}"
        ),
        "sport": sport,
        "division": division,
        "scholarship_cap_equivalencies": scholarship_cap_equivalencies,
        "roster_cap_count": roster_cap_count,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# RecruitingCalendar — PRD §3.1
# ---------------------------------------------------------------------------
def create_recruiting_calendar_payload(
    *,
    program_id: str,
    period_type: str = "CONTACT",
    start_date: str,
    end_date: str,
    note: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /recruiting-calendars — ComplianceOfficer only.

    PRD §3.1: required input fields are program_id, period_type,
    start_date, end_date. note is optional.
    """
    payload: Dict[str, Any] = {
        "program_id": program_id,
        "period_type": period_type,
        "start_date": start_date,
        "end_date": end_date,
    }
    if note is not None:
        payload["note"] = note
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Athlete — PRD §3.2
# ---------------------------------------------------------------------------
def create_athlete_payload(
    *,
    full_name: Optional[str] = None,
    high_school: str = "Anywhere High",
    graduation_year: int = 2025,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /athletes — ComplianceOfficer or Coach.

    PRD §3.2: required input fields are full_name, high_school,
    graduation_year.
    """
    payload: Dict[str, Any] = {
        "full_name": (
            full_name if full_name is not None
            else f"Athlete {random_suffix(4)}"
        ),
        "high_school": high_school,
        "graduation_year": graduation_year,
    }
    payload.update(overrides)
    return payload


def transition_athlete_payload(
    *,
    to_status: str,
    program_id: Optional[str] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /athletes/{id}/state — ComplianceOfficer only.

    PRD §2.5: state-transition endpoints require to_status; version is
    optional. PRD §3.2: PROSPECTIVE->COMMITTED requires program_id.
    """
    payload: Dict[str, Any] = {"to_status": to_status}
    if program_id is not None:
        payload["program_id"] = program_id
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# EligibilityRecord — PRD §3.2
# ---------------------------------------------------------------------------
def create_eligibility_record_payload(
    *,
    athlete_id: str,
    core_gpa: float = 3.50,
    standardized_test_score: int = 1200,
    core_courses_completed: int = 16,
    decision: str = "QUALIFIER",
    decided_at: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /eligibility-records — ComplianceOfficer only.

    PRD §3.2: required input fields are athlete_id, core_gpa,
    standardized_test_score, core_courses_completed, decision, decided_at.
    """
    payload: Dict[str, Any] = {
        "athlete_id": athlete_id,
        "core_gpa": core_gpa,
        "standardized_test_score": standardized_test_score,
        "core_courses_completed": core_courses_completed,
        "decision": decision,
        "decided_at": decided_at or iso_now(),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ScholarshipSlot — PRD §3.3
# ---------------------------------------------------------------------------
def create_scholarship_slot_payload(
    *,
    program_id: str,
    athlete_id: str,
    fractional_equivalency: float = 1.00,
    annual_value_cents: int = 5_000_000,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /scholarship-slots — Coach only.

    PRD §3.3: required input fields are program_id, athlete_id,
    fractional_equivalency (in [0.01, 1.00] at two decimal places),
    annual_value_cents.
    """
    payload: Dict[str, Any] = {
        "program_id": program_id,
        "athlete_id": athlete_id,
        "fractional_equivalency": fractional_equivalency,
        "annual_value_cents": annual_value_cents,
    }
    payload.update(overrides)
    return payload


def transition_scholarship_slot_payload(
    *,
    to_status: str,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /scholarship-slots/{id}/state — Coach or ComplianceOfficer.

    PRD §2.5: state-transition endpoints require to_status.
    """
    payload: Dict[str, Any] = {"to_status": to_status}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# RecruitingContact — PRD §3.8
# ---------------------------------------------------------------------------
def create_recruiting_contact_payload(
    *,
    program_id: str,
    athlete_id: str,
    contact_type: str = "PHONE_CALL",
    contact_at: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /recruiting-contacts — Coach only.

    PRD §3.8: required input fields are program_id, athlete_id,
    contact_type, contact_at.
    """
    payload: Dict[str, Any] = {
        "program_id": program_id,
        "athlete_id": athlete_id,
        "contact_type": contact_type,
        "contact_at": contact_at or iso_now(),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# NILDeal — PRD §3.5
# ---------------------------------------------------------------------------
def create_nil_deal_payload(
    *,
    athlete_id: str,
    sponsor_name: Optional[str] = None,
    sponsor_is_booster: bool = False,
    deal_category: str = "ENDORSEMENT",
    stated_value_cents: int = 500_000,
    deliverables_hours: float = 10.0,
    market_rate_cents_per_hour: int = 50_000,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /nil-deals — Athlete, Booster, or ComplianceOfficer.

    PRD §3.5: required input fields are athlete_id, sponsor_name,
    sponsor_is_booster, deal_category, stated_value_cents,
    deliverables_hours, market_rate_cents_per_hour.
    """
    payload: Dict[str, Any] = {
        "athlete_id": athlete_id,
        "sponsor_name": (
            sponsor_name if sponsor_name is not None
            else f"Sponsor {random_suffix(4)}"
        ),
        "sponsor_is_booster": sponsor_is_booster,
        "deal_category": deal_category,
        "stated_value_cents": stated_value_cents,
        "deliverables_hours": deliverables_hours,
        "market_rate_cents_per_hour": market_rate_cents_per_hour,
    }
    payload.update(overrides)
    return payload


def patch_nil_deal_payload(
    *,
    deliverables_hours: Optional[float] = None,
    market_rate_cents_per_hour: Optional[int] = None,
    stated_value_cents: Optional[int] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PATCH /nil-deals/{id} — Athlete, Booster, or ComplianceOfficer.

    PRD §3.5: editable fields while SUBMITTED are deliverables_hours,
    market_rate_cents_per_hour, stated_value_cents. PRD §2.5: version is
    optional; if supplied and stale, request is rejected with
    ERR_VERSION_MISMATCH.
    """
    payload: Dict[str, Any] = {}
    if deliverables_hours is not None:
        payload["deliverables_hours"] = deliverables_hours
    if market_rate_cents_per_hour is not None:
        payload["market_rate_cents_per_hour"] = market_rate_cents_per_hour
    if stated_value_cents is not None:
        payload["stated_value_cents"] = stated_value_cents
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def transition_nil_deal_payload(
    *,
    to_status: str,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /nil-deals/{id}/state — ComplianceOfficer only.

    PRD §2.5: state-transition endpoints require to_status.
    """
    payload: Dict[str, Any] = {"to_status": to_status}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# TransferPortalEntry — PRD §3.4
# ---------------------------------------------------------------------------
def create_transfer_portal_entry_payload(
    *,
    athlete_id: str,
    reason: str = "PLAYING_TIME",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /transfer-portal-entries — Athlete or ComplianceOfficer.

    PRD §3.4: required input fields are athlete_id and reason (one of
    PLAYING_TIME, COACHING_CHANGE, FAMILY, ACADEMIC, OTHER).
    """
    payload: Dict[str, Any] = {
        "athlete_id": athlete_id,
        "reason": reason,
    }
    payload.update(overrides)
    return payload


def transition_transfer_portal_entry_payload(
    *,
    to_status: str,
    destination_program_id: Optional[str] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /transfer-portal-entries/{id}/state — ComplianceOfficer or
    Athlete.

    PRD §3.4: CONTACT_WINDOW->COMMITTED requires destination_program_id.
    """
    payload: Dict[str, Any] = {"to_status": to_status}
    if destination_program_id is not None:
        payload["destination_program_id"] = destination_program_id
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ComplianceViolation — PRD §3.7
# ---------------------------------------------------------------------------
def create_violation_payload(
    *,
    program_id: str,
    subject_type: str = "BOOSTER",
    subject_ref: Optional[str] = None,
    violation_type: str = "IMPERMISSIBLE_BENEFIT",
    severity: str = "LEVEL_II",
    related_athlete_id: Optional[str] = None,
    related_deal_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /violations — ComplianceOfficer or Auditor.

    PRD §3.7: required input fields are program_id, subject_type,
    subject_ref, violation_type, severity. related_athlete_id and
    related_deal_id are optional FKs.
    """
    payload: Dict[str, Any] = {
        "program_id": program_id,
        "subject_type": subject_type,
        "subject_ref": (
            subject_ref if subject_ref is not None
            else f"subject-{random_suffix(4)}"
        ),
        "violation_type": violation_type,
        "severity": severity,
    }
    if related_athlete_id is not None:
        payload["related_athlete_id"] = related_athlete_id
    if related_deal_id is not None:
        payload["related_deal_id"] = related_deal_id
    payload.update(overrides)
    return payload


def transition_violation_payload(
    *,
    to_status: str,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /violations/{id}/state — ComplianceOfficer or Coach (Coach
    only for APPEALED per PRD §3.7 / RBAC matrix).
    """
    payload: Dict[str, Any] = {"to_status": to_status}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock advance — PRD §2.10
# ---------------------------------------------------------------------------
def advance_clock_payload(
    *,
    to_timestamp: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /_clock/advance — ComplianceOfficer or Auditor.

    PRD §2.10: required input field is to_timestamp.
    """
    payload: Dict[str, Any] = {"to_timestamp": to_timestamp}
    payload.update(overrides)
    return payload


__all__ = [
    "iso_utc",
    "utcnow",
    "iso_now",
    "iso_offset",
    "random_suffix",
    "create_program_payload",
    "create_recruiting_calendar_payload",
    "create_athlete_payload",
    "transition_athlete_payload",
    "create_eligibility_record_payload",
    "create_scholarship_slot_payload",
    "transition_scholarship_slot_payload",
    "create_recruiting_contact_payload",
    "create_nil_deal_payload",
    "patch_nil_deal_payload",
    "transition_nil_deal_payload",
    "create_transfer_portal_entry_payload",
    "transition_transfer_portal_entry_payload",
    "create_violation_payload",
    "transition_violation_payload",
    "advance_clock_payload",
]
