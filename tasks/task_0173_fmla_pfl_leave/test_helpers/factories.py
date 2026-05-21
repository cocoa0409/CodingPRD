"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the JSON-body schema the PRD declares for the
request body (PRD §3 narratives + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed / system fields are intentionally
omitted.

PRD §2.2: timestamps are ISO 8601 UTC with three fractional digits.
PRD §2.7: hours are whole integers; cents are whole integers; calendar
days are whole days (YYYY-MM-DD).
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Time helpers — PRD §2.2 ISO 8601 UTC with three fractional digits.
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


def parse_iso(iso_ts: str) -> datetime:
    """Parse an ISO 8601 string accepting both 'Z' and '+00:00' offsets."""
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


def add_seconds(iso_ts: str, seconds: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(seconds=seconds))


def add_minutes(iso_ts: str, minutes: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(minutes=minutes))


def add_days(iso_ts: str, days: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(days=days))


def date_str(year: int, month: int, day: int) -> str:
    """Return an ISO calendar date YYYY-MM-DD (no time)."""
    return f"{year:04d}-{month:02d}-{day:02d}"


def date_to_iso_midnight(d: date) -> str:
    """Return ISO 8601 UTC at midnight for a calendar date."""
    return iso_utc(datetime(d.year, d.month, d.day, tzinfo=timezone.utc))


# ---------------------------------------------------------------------------
# Random suffix — for cross-test uniqueness.
# ---------------------------------------------------------------------------
def random_suffix(n: int = 8) -> str:
    return "".join(
        random.choices(string.ascii_lowercase + string.digits, k=n)
    )


# ---------------------------------------------------------------------------
# Employer — POST /employers
# PRD §3.1: legal_name, leave_year_basis, state_pfl_program,
# benefit_premium_share_cents.
# ---------------------------------------------------------------------------
def create_employer_payload(
    *,
    legal_name: Optional[str] = None,
    leave_year_basis: str = "CALENDAR",
    state_pfl_program: str = "NONE",
    benefit_premium_share_cents: Optional[int] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": (
            legal_name or f"{TEST_DEFAULTS['EMPLOYER_LEGAL_NAME']}-{random_suffix(4)}"
        ),
        "leave_year_basis": leave_year_basis,
        "state_pfl_program": state_pfl_program,
        "benefit_premium_share_cents": (
            benefit_premium_share_cents
            if benefit_premium_share_cents is not None
            else TEST_DEFAULTS["BENEFIT_PREMIUM_SHARE_CENTS"]
        ),
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Worksite — POST /employers/{employer_id}/worksites
# PRD §3.1: address_line, employee_count_within_75_miles.
# ---------------------------------------------------------------------------
def create_worksite_payload(
    *,
    address_line: Optional[str] = None,
    employee_count_within_75_miles: Optional[int] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "address_line": address_line or TEST_DEFAULTS["WORKSITE_ADDRESS"],
        "employee_count_within_75_miles": (
            employee_count_within_75_miles
            if employee_count_within_75_miles is not None
            else TEST_DEFAULTS["WORKSITE_HEADCOUNT"]
        ),
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Worksite PATCH — PATCH /worksites/{id}
# PRD §3.1: update employee_count_within_75_miles + version.
# ---------------------------------------------------------------------------
def patch_worksite_payload(
    *,
    employee_count_within_75_miles: int,
    version: Optional[int] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "employee_count_within_75_miles": employee_count_within_75_miles,
    }
    if version is not None:
        payload["version"] = version
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Employee — POST /employers/{employer_id}/employees
# PRD §3.1: worksite_id, full_name, hire_date, hours_worked_trailing_12mo,
# monthly_wage_cents.
# ---------------------------------------------------------------------------
def create_employee_payload(
    *,
    worksite_id: str,
    full_name: Optional[str] = None,
    hire_date: Optional[str] = None,
    hours_worked_trailing_12mo: Optional[int] = None,
    monthly_wage_cents: Optional[int] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "worksite_id": worksite_id,
        "full_name": (
            full_name or f"{TEST_DEFAULTS['EMPLOYEE_FULL_NAME']}-{random_suffix(4)}"
        ),
        "hire_date": hire_date or TEST_DEFAULTS["EMPLOYEE_HIRE_DATE"],
        "hours_worked_trailing_12mo": (
            hours_worked_trailing_12mo
            if hours_worked_trailing_12mo is not None
            else TEST_DEFAULTS["EMPLOYEE_HOURS_TRAILING_12MO"]
        ),
        "monthly_wage_cents": (
            monthly_wage_cents
            if monthly_wage_cents is not None
            else TEST_DEFAULTS["EMPLOYEE_MONTHLY_WAGE_CENTS"]
        ),
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Hours snapshot — POST /employees/{id}/hours-snapshot
# PRD §3.1: writes hours_worked_trailing_12mo.
# ---------------------------------------------------------------------------
def hours_snapshot_payload(
    *,
    hours_worked_trailing_12mo: int,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "hours_worked_trailing_12mo": hours_worked_trailing_12mo,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# LeaveCase — POST /employees/{id}/leave-cases
# PRD §3.3: reason, leave_pattern, requested_start_date, expected_end_date,
# pfl_claim_id?.
# ---------------------------------------------------------------------------
def create_leave_case_payload(
    *,
    reason: str,
    leave_pattern: str,
    requested_start_date: str,
    expected_end_date: str,
    pfl_claim_id: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "reason": reason,
        "leave_pattern": leave_pattern,
        "requested_start_date": requested_start_date,
        "expected_end_date": expected_end_date,
    }
    if pfl_claim_id is not None:
        payload["pfl_claim_id"] = pfl_claim_id
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# LeaveCase review — POST /leave-cases/{id}/review
# PRD §3.6: decision in {APPROVE, DENY}.
# ---------------------------------------------------------------------------
def review_leave_case_payload(
    *,
    decision: str,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# LeaveCase cancel — DELETE /leave-cases/{id}
# PRD §3.11: optional version for OCC.
# ---------------------------------------------------------------------------
def cancel_leave_case_payload(
    *,
    version: Optional[int] = None,
    **extra: Any,
) -> Optional[Dict[str, Any]]:
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    payload.update(extra)
    return payload if payload else None


# ---------------------------------------------------------------------------
# LeaveInstance — POST /leave-cases/{id}/instances
# PRD §3.4: instance_date (YYYY-MM-DD), hours_used (1..24).
# ---------------------------------------------------------------------------
def create_leave_instance_payload(
    *,
    instance_date: str,
    hours_used: int,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "instance_date": instance_date,
        "hours_used": hours_used,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# MedicalCertification — POST /leave-cases/{id}/certifications
# PRD §3.5: serious_health_condition (bool),
# estimated_frequency_per_month? (default 0), estimated_duration_hours?
# (default 0).
# ---------------------------------------------------------------------------
def create_certification_payload(
    *,
    serious_health_condition: bool,
    estimated_frequency_per_month: Optional[int] = None,
    estimated_duration_hours: Optional[int] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "serious_health_condition": serious_health_condition,
    }
    if estimated_frequency_per_month is not None:
        payload["estimated_frequency_per_month"] = estimated_frequency_per_month
    if estimated_duration_hours is not None:
        payload["estimated_duration_hours"] = estimated_duration_hours
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# MedicalCertification review — POST .../certifications/{cert_id}/review
# PRD §3.5: decision in {ACCEPT, INSUFFICIENT, REJECT}.
# ---------------------------------------------------------------------------
def review_certification_payload(
    *,
    decision: str,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# PfLClaim — POST /pfl-claims
# PRD §3.8: employee_id, claim_type, weeks_authorized (1..8).
# ---------------------------------------------------------------------------
def create_pfl_claim_payload(
    *,
    employee_id: str,
    claim_type: str,
    weeks_authorized: int,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "employee_id": employee_id,
        "claim_type": claim_type,
        "weeks_authorized": weeks_authorized,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Clock advance — POST /_clock/advance
# PRD §2.10: "A dedicated administrative capability advances that
# clock to a supplied target instant".
# ---------------------------------------------------------------------------
def clock_advance_payload(
    *,
    to_timestamp: str,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_timestamp": to_timestamp}
    payload.update(extra)
    return payload


__all__ = [
    # Time helpers
    "iso_utc", "utcnow", "iso_now", "parse_iso",
    "add_seconds", "add_minutes", "add_days",
    "date_str", "date_to_iso_midnight",
    # Randomness
    "random_suffix",
    # Payload factories
    "create_employer_payload",
    "create_worksite_payload",
    "patch_worksite_payload",
    "create_employee_payload",
    "hours_snapshot_payload",
    "create_leave_case_payload",
    "review_leave_case_payload",
    "cancel_leave_case_payload",
    "create_leave_instance_payload",
    "create_certification_payload",
    "review_certification_payload",
    "create_pfl_claim_payload",
    "clock_advance_payload",
]
