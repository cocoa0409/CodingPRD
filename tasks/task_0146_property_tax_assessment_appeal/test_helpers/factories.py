"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body (PRD §3 narrative + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed/system fields are intentionally omitted
so the implementation cannot accidentally accept them as inputs.

PRD §2.6: all money is JSON number with at most two decimal places.
PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Random helpers
# ---------------------------------------------------------------------------
def random_suffix(n: int = 8) -> str:
    return "".join(
        random.choices(string.ascii_lowercase + string.digits, k=n),
    )


def random_full_name(prefix: str = "Test Owner") -> str:
    return f"{prefix} {random_suffix(6)}"


def random_parcel_number(prefix: str = "PARCEL") -> str:
    return f"{prefix}-{random_suffix(8).upper()}"


# ---------------------------------------------------------------------------
# Date / time helpers — PRD §2.6, §2.11
# ---------------------------------------------------------------------------
def iso_date_str(d: date) -> str:
    """ISO 8601 calendar date in YYYY-MM-DD form."""
    return d.isoformat()


def iso_datetime_utc(year: int, month: int, day: int,
                     hour: int = 0, minute: int = 0,
                     second: int = 0,
                     millis: int = 0) -> str:
    """ISO 8601 UTC instant with three fractional digits. PRD §2.4."""
    return (
        f"{year:04d}-{month:02d}-{day:02d}"
        f"T{hour:02d}:{minute:02d}:{second:02d}.{millis:03d}Z"
    )


def iso_from_dt(dt: datetime) -> str:
    """Format a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def iso_now_utc() -> str:
    """Current UTC instant in PRD §2.2 format."""
    return iso_from_dt(datetime.now(tz=timezone.utc))


def add_days_iso(base_iso: str, days: int) -> str:
    """Take an ISO 8601 timestamp and add days; return ISO."""
    dt = _parse_iso(base_iso)
    return iso_from_dt(dt + timedelta(days=days))


def add_minutes_iso(base_iso: str, minutes: int) -> str:
    """Take an ISO 8601 timestamp and add minutes; return ISO."""
    dt = _parse_iso(base_iso)
    return iso_from_dt(dt + timedelta(minutes=minutes))


def add_milliseconds_iso(base_iso: str, ms: int) -> str:
    """Take an ISO 8601 timestamp and add milliseconds; return ISO."""
    dt = _parse_iso(base_iso)
    return iso_from_dt(dt + timedelta(milliseconds=ms))


def _parse_iso(s: str) -> datetime:
    """Tolerant ISO 8601 parser for the formats this PRD emits."""
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


# ===========================================================================
# Owner — PRD §3.1
# ===========================================================================
def create_owner_payload(
    *,
    full_name: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    veteran_status: Optional[bool] = None,
    disability_rating: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD §3.1 inputs: full_name, date_of_birth; optional
    veteran_status (default false), disability_rating (default 0).
    """
    payload: Dict[str, Any] = {
        "full_name": full_name if full_name is not None else random_full_name(),
        "date_of_birth": (
            date_of_birth if date_of_birth is not None
            else iso_date_str(date(1980, 1, 1))
        ),
    }
    if veteran_status is not None:
        payload["veteran_status"] = veteran_status
    if disability_rating is not None:
        payload["disability_rating"] = disability_rating
    return payload


# ===========================================================================
# HearingOfficer — PRD §3.1
# ===========================================================================
def create_hearing_officer_payload(
    *,
    full_name: Optional[str] = None,
    active: Optional[bool] = None,
) -> Dict[str, Any]:
    """PRD §3.1: 'A Treasurer may register a HearingOfficer with
    full_name and an optional active flag (default true).'"""
    payload: Dict[str, Any] = {
        "full_name": (
            full_name if full_name is not None
            else random_full_name(prefix="Officer")
        ),
    }
    if active is not None:
        payload["active"] = active
    return payload


# ===========================================================================
# Property — PRD §3.1
# ===========================================================================
def create_property_payload(
    *,
    owner_id: str,
    parcel_number: Optional[str] = None,
    market_value: float = 500_000.00,
) -> Dict[str, Any]:
    """PRD §3.1: 'Property registration is the responsibility of the
    Assessor, who supplies owner_id, parcel_number, and market_value.'"""
    return {
        "owner_id": owner_id,
        "parcel_number": (
            parcel_number if parcel_number is not None
            else random_parcel_number()
        ),
        "market_value": market_value,
    }


def transfer_owner_payload(*, new_owner_id: str,
                           version: Optional[int] = None,
                           ) -> Dict[str, Any]:
    """PRD §3.1: 'Ownership transfers are also performed by the
    Assessor, who supplies a new new_owner_id and the property's
    current version.'"""
    payload: Dict[str, Any] = {"new_owner_id": new_owner_id}
    if version is not None:
        payload["version"] = version
    return payload


# ===========================================================================
# Assessment — PRD §3.2
# ===========================================================================
def create_assessment_payload(
    *,
    roll_year: int,
    market_value_at_roll: float,
) -> Dict[str, Any]:
    """PRD §3.2: 'An Assessor first creates an Assessment in DRAFT by
    supplying roll_year and market_value_at_roll.'"""
    return {
        "roll_year": roll_year,
        "market_value_at_roll": market_value_at_roll,
    }


# ===========================================================================
# ExemptionApplication — PRD §3.3
# ===========================================================================
def submit_exemption_payload(
    *,
    exemption_type: str,
    effective_roll_year: int,
) -> Dict[str, Any]:
    """PRD §3.3: 'An Owner files an ExemptionApplication by supplying
    exemption_type and effective_roll_year.'"""
    return {
        "exemption_type": exemption_type,
        "effective_roll_year": effective_roll_year,
    }


def revoke_exemption_payload(
    *,
    revoked_reason: str,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD §3.3: 'the revoke call requires revoked_reason to be
    supplied' (one of OWNERSHIP_CHANGE, INELIGIBLE, WITHDRAWN)."""
    payload: Dict[str, Any] = {"revoked_reason": revoked_reason}
    if version is not None:
        payload["version"] = version
    return payload


# ===========================================================================
# Appeal — PRD §3.5
# ===========================================================================
def file_appeal_payload(
    *,
    assessment_id: str,
    filed_grounds: str = "OVER_MARKET",
    claimed_value: float = 0.00,
) -> Dict[str, Any]:
    """PRD §3.5: 'Filing an Appeal requires an Owner to supply
    assessment_id, filed_grounds (one of OVER_MARKET, EXEMPTION_DENIED,
    CAP_MISAPPLIED, or CLERICAL_ERROR), and claimed_value.'"""
    return {
        "assessment_id": assessment_id,
        "filed_grounds": filed_grounds,
        "claimed_value": claimed_value,
    }


def schedule_appeal_payload(
    *,
    scheduled_start: str,
    scheduled_end: str,
    hearing_room: str,
    officer_id: str,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD §3.5: '(Treasurer) supplies scheduled_start, scheduled_end,
    hearing_room, officer_id, and an optional version.'"""
    payload: Dict[str, Any] = {
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "hearing_room": hearing_room,
        "officer_id": officer_id,
    }
    if version is not None:
        payload["version"] = version
    return payload


def decide_appeal_payload(
    *,
    decision_outcome: str,
    decided_value: float,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD §3.5: '(HearingOfficer) requires decision_outcome (one of
    UPHELD, REDUCED, or INCREASED), decided_value, and an optional
    version.'"""
    payload: Dict[str, Any] = {
        "decision_outcome": decision_outcome,
        "decided_value": decided_value,
    }
    if version is not None:
        payload["version"] = version
    return payload


# ===========================================================================
# TaxBill — PRD §3.4
# ===========================================================================
def create_tax_bill_payload(
    *,
    roll_year: int,
    mill_rate: Optional[float] = None,
) -> Dict[str, Any]:
    """PRD §3.4: 'The treasurer supplies roll_year and may optionally
    supply mill_rate.'"""
    payload: Dict[str, Any] = {"roll_year": roll_year}
    if mill_rate is not None:
        payload["mill_rate"] = mill_rate
    return payload


def create_payment_payload(*, amount: float) -> Dict[str, Any]:
    """PRD §3.4: 'Each payment carries only an amount.'"""
    return {"amount": amount}


# ===========================================================================
# Clock advance — PRD §2.11
# ===========================================================================
def clock_advance_payload(*, target_timestamp: str) -> Dict[str, Any]:
    """PRD §2.11: 'advances a logical server clock to a supplied
    target_timestamp'."""
    return {"target_timestamp": target_timestamp}


# ===========================================================================
# Optional-version helper — PRD §2.10
# ===========================================================================
def version_body(version: Optional[int]) -> Dict[str, Any]:
    """Build an OCC body fragment carrying `version` only when supplied.

    PRD §2.10: 'All transition endpoints that accept a request body
    permit an optional version field. When version is supplied, the
    server compares it against the target resource's current version;
    a mismatch fails the request with ERR_VERSION_MISMATCH.'
    """
    return {"version": version} if version is not None else {}


__all__ = [
    # randomness / time
    "random_suffix",
    "random_full_name",
    "random_parcel_number",
    "iso_date_str",
    "iso_datetime_utc",
    "iso_from_dt",
    "iso_now_utc",
    "add_days_iso",
    "add_minutes_iso",
    "add_milliseconds_iso",
    # payload factories
    "create_owner_payload",
    "create_hearing_officer_payload",
    "create_property_payload",
    "transfer_owner_payload",
    "create_assessment_payload",
    "submit_exemption_payload",
    "revoke_exemption_payload",
    "file_appeal_payload",
    "schedule_appeal_payload",
    "decide_appeal_payload",
    "create_tax_bill_payload",
    "create_payment_payload",
    "clock_advance_payload",
    "version_body",
]
