"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body (PRD §3 narrative + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed/system fields are intentionally omitted so
the implementation cannot accidentally accept them as inputs.

PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
PRD §2.10: monetary fields are integer cents.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .constants import TEST_DEFAULTS, DAYS_PER_YEAR


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


# ---------------------------------------------------------------------------
# ISO date helpers — for fields PRD declares as YYYY-MM-DD calendar dates
# (Child.date_of_birth, Session.reference_date, Session.week_start,
# SessionDay.day_date, GET /camp/families/{id}/invoice?week_start=).
# ---------------------------------------------------------------------------
def iso_date(d: date) -> str:
    return d.isoformat()


def date_today_utc() -> date:
    return datetime.now(tz=timezone.utc).date()


def date_offset(*, days: int = 0, base: Optional[date] = None) -> date:
    base = base or date_today_utc()
    return base + timedelta(days=days)


def previous_monday(base: Optional[date] = None) -> date:
    """Return the Monday on or before `base`. PRD §3.3:
    week_start must fall on a Monday.
    """
    base = base or date_today_utc()
    return base - timedelta(days=base.weekday())


def next_monday(base: Optional[date] = None) -> date:
    """Return the next Monday strictly after `base`."""
    base = base or date_today_utc()
    days_ahead = 7 - base.weekday()
    return base + timedelta(days=days_ahead)


def dob_for_age(target_age: int,
                reference: Optional[date] = None) -> str:
    """Compute a date_of_birth (ISO 8601 YYYY-MM-DD) such that the child
    is exactly `target_age` whole years old on `reference` using PRD's
    age formula (floor((reference - dob) / 365.2425)).

    Returns date offset by target_age * 365.2425 + 30 days back to give
    a stable in-band age, well inside the floor boundary.
    """
    reference = reference or date_today_utc()
    days_back = int(target_age * DAYS_PER_YEAR) + 30
    return iso_date(reference - timedelta(days=days_back))


_ALPHANUM = string.ascii_uppercase + string.digits


def random_suffix(n: int = 8) -> str:
    return "".join(random.choices(_ALPHANUM, k=n))


def random_email(prefix: str = "user") -> str:
    return f"{prefix}_{random_suffix(8).lower()}@test.example"


def random_phone() -> str:
    """E.164-style phone, 8-20 chars per PRD §3.1 / §3.2."""
    return "+1" + "".join(random.choices(string.digits, k=10))


# ---------------------------------------------------------------------------
# Family — PRD §3.1
# ---------------------------------------------------------------------------
def create_family_payload(
    *,
    household_name: Optional[str] = None,
    primary_email: Optional[str] = None,
    residency_status: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /camp/families — ProgramAdmin.

    PRD §3.1: required input fields are household_name (1-100 chars) and
    primary_email (lower-cased, unique among non-archived families).
    PRD §3.1: residency_status is OPTIONAL with default STANDARD.
    """
    payload: Dict[str, Any] = {
        "household_name": (
            household_name if household_name is not None
            else f"Family {random_suffix(4)}"
        ),
        "primary_email": primary_email or random_email("family"),
    }
    if residency_status is not None:
        payload["residency_status"] = residency_status
    payload.update(overrides)
    return payload


def patch_family_payload(
    *,
    version: Optional[int] = None,
    household_name: Optional[str] = None,
    primary_email: Optional[str] = None,
    residency_status: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PATCH /camp/families/{id} — ProgramAdmin.

    PRD §2.5 + §3.1: the modification request may carry the current
    `version` in the body to clear the OCC check; PRD §2.5: "When the
    client omits version from the body entirely, no concurrency check
    is performed." All other fields are optional updates.
    """
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    if household_name is not None:
        payload["household_name"] = household_name
    if primary_email is not None:
        payload["primary_email"] = primary_email
    if residency_status is not None:
        payload["residency_status"] = residency_status
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Guardian — PRD §3.1
# ---------------------------------------------------------------------------
def create_guardian_payload(
    *,
    full_name: Optional[str] = None,
    phone: Optional[str] = None,
    relationship: str = "PARENT",
    is_primary: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /camp/families/{family_id}/guardians — ProgramAdmin or
    Guardian.

    PRD §3.1: required input fields are full_name (1-100 chars), phone
    (E.164-style, 8-20 chars), relationship in {PARENT, STEP_PARENT,
    LEGAL_GUARDIAN, OTHER}. is_primary is OPTIONAL; if omitted the new
    guardian defaults to non-primary.
    """
    payload: Dict[str, Any] = {
        "full_name": (
            full_name if full_name is not None
            else f"Guardian {random_suffix(4)}"
        ),
        "phone": phone or random_phone(),
        "relationship": relationship,
    }
    if is_primary is not None:
        payload["is_primary"] = is_primary
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Child — PRD §3.1
# ---------------------------------------------------------------------------
def create_child_payload(
    *,
    full_name: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    age_years: Optional[int] = None,
    reference_date: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /camp/families/{family_id}/children — ProgramAdmin or
    Guardian.

    PRD §3.1: required input fields are full_name (1-100 chars) and
    date_of_birth (ISO 8601 YYYY-MM-DD, strictly in the past relative
    to the current logical clock).

    Convenience: pass age_years to derive a date_of_birth that makes the
    child exactly age_years old on `reference_date` (defaults to today).
    """
    if date_of_birth is None:
        age = age_years if age_years is not None else TEST_DEFAULTS[
            "CHILD_AGE_YEARS"
        ]
        ref: Optional[date] = None
        if reference_date is not None:
            ref = date.fromisoformat(reference_date)
        date_of_birth = dob_for_age(age, reference=ref)
    payload: Dict[str, Any] = {
        "full_name": (
            full_name if full_name is not None
            else f"Child {random_suffix(4)}"
        ),
        "date_of_birth": date_of_birth,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# EmergencyContact — PRD §3.2
# ---------------------------------------------------------------------------
def create_emergency_contact_payload(
    *,
    full_name: Optional[str] = None,
    phone: Optional[str] = None,
    relationship: str = "aunt",
    priority: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /camp/children/{child_id}/emergency-contacts — ProgramAdmin
    or Guardian.

    PRD §3.2: required input fields are full_name (1-100 chars), phone
    (E.164-style, 8-20 chars), relationship (free-text 1-60 chars),
    priority (integer 1-9 inclusive).
    """
    payload: Dict[str, Any] = {
        "full_name": (
            full_name if full_name is not None
            else f"Contact {random_suffix(4)}"
        ),
        "phone": phone or random_phone(),
        "relationship": relationship,
        "priority": priority,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Authorization — PRD §3.2
# ---------------------------------------------------------------------------
def create_authorization_payload(
    *,
    guardian_id: str,
    kind: str = "MEDICAL",
    scope_text: str = "Treatment authorization for camp activities.",
    effective_at: Optional[str] = None,
    expires_at: Optional[str] = None,
    effective_offset_minutes: int = -60,
    expires_offset_days: int = 365,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /camp/children/{child_id}/authorizations — ProgramAdmin or
    Guardian.

    PRD §3.2: required input fields are guardian_id (must belong to the
    same family as the child, else ERR_FAMILY_MISMATCH), kind (MEDICAL
    or PICKUP), scope_text (1-500 chars), effective_at (datetime),
    expires_at (datetime, strictly greater than effective_at — else
    ERR_INVALID_TIME_RANGE).

    Convenience: by default effective_at is 60 minutes in the past and
    expires_at is 365 days in the future, so the authorization is
    immediately ACTIVE on the current clock and the
    effective_at < expires_at constraint is trivially satisfied.
    """
    if effective_at is None:
        effective_at = iso_offset(minutes=effective_offset_minutes)
    if expires_at is None:
        expires_at = iso_offset(days=expires_offset_days)
    payload: Dict[str, Any] = {
        "guardian_id": guardian_id,
        "kind": kind,
        "scope_text": scope_text,
        "effective_at": effective_at,
        "expires_at": expires_at,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Session — PRD §3.3
# ---------------------------------------------------------------------------
def create_session_payload(
    *,
    title: Optional[str] = None,
    kind: str = "AFTERSCHOOL",
    age_min: int = 5,
    age_max: int = 12,
    reference_date: Optional[str] = None,
    weekly_capacity: int = 10,
    week_start: Optional[str] = None,
    week_count: int = 1,
    base_weekly_fee_cents: int = 10_000,
    rainy_day_pool_per_week: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /camp/sessions — ProgramAdmin.

    PRD §3.3: required input fields are title (1-120 chars), kind
    (AFTERSCHOOL or SUMMER_CAMP), age_min and age_max (both in [3, 17],
    age_min <= age_max), reference_date (ISO date), weekly_capacity
    (1-200), week_start (Monday ISO date), week_count (1-12),
    base_weekly_fee_cents (>= 0), rainy_day_pool_per_week (0 <= rdp <=
    weekly_capacity).
    """
    if week_start is None:
        # Default to next Monday so week_start lies in the future and
        # the session can be opened and tested under the current clock.
        week_start = iso_date(next_monday())
    if reference_date is None:
        # Default reference_date to the same week_start so age math is
        # stable across runs.
        reference_date = week_start
    payload: Dict[str, Any] = {
        "title": (
            title if title is not None
            else f"Session {random_suffix(4)}"
        ),
        "kind": kind,
        "age_min": age_min,
        "age_max": age_max,
        "reference_date": reference_date,
        "weekly_capacity": weekly_capacity,
        "week_start": week_start,
        "week_count": week_count,
        "base_weekly_fee_cents": base_weekly_fee_cents,
        "rainy_day_pool_per_week": rainy_day_pool_per_week,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Enrollment — PRD §3.4
# ---------------------------------------------------------------------------
def create_enrollment_payload(
    *,
    child_id: str,
    session_id: str,
    week_index: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /camp/enrollments — ProgramAdmin or Guardian.

    PRD §3.4: required input fields are child_id, session_id, week_index
    (integer in [0, Session.week_count)).
    """
    payload: Dict[str, Any] = {
        "child_id": child_id,
        "session_id": session_id,
        "week_index": week_index,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ScholarshipAward — PRD §3.6
# ---------------------------------------------------------------------------
def create_scholarship_payload(
    *,
    total_credit_cents: int = 5_000,
    granted_for_kind: str = "ANY",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /camp/families/{family_id}/scholarships — ProgramAdmin.

    PRD §3.6: required input fields are total_credit_cents (at least 1)
    and granted_for_kind in {AFTERSCHOOL, SUMMER_CAMP, ANY}.
    """
    payload: Dict[str, Any] = {
        "total_credit_cents": total_credit_cents,
        "granted_for_kind": granted_for_kind,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# SessionDay weather — PRD §3.8
# ---------------------------------------------------------------------------
def set_weather_payload(
    *,
    weather_status: str = "RAINY",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /camp/session-days/{id}/set-weather — ProgramAdmin.

    PRD §3.8: required input is weather_status in {NORMAL, RAINY,
    CLOSED}.
    """
    payload: Dict[str, Any] = {"weather_status": weather_status}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock advance — PRD §2.7
# ---------------------------------------------------------------------------
def clock_advance_payload(
    *,
    iso_timestamp: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /_clock/advance — ProgramAdmin.

    PRD §2.7: required input is iso_timestamp (ISO 8601 UTC instant).
    """
    payload: Dict[str, Any] = {"iso_timestamp": iso_timestamp}
    payload.update(overrides)
    return payload


__all__ = [
    "iso_utc",
    "utcnow",
    "iso_now",
    "iso_offset",
    "parse_iso",
    "iso_date",
    "date_today_utc",
    "date_offset",
    "previous_monday",
    "next_monday",
    "dob_for_age",
    "random_suffix",
    "random_email",
    "random_phone",
    "create_family_payload",
    "patch_family_payload",
    "create_guardian_payload",
    "create_child_payload",
    "create_emergency_contact_payload",
    "create_authorization_payload",
    "create_session_payload",
    "create_enrollment_payload",
    "create_scholarship_payload",
    "set_weather_payload",
    "clock_advance_payload",
]
