"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the JSON-body schema the PRD declares for the
request body (PRD §3 narratives + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed / system fields are intentionally
omitted.

PRD §2.6: timestamps are ISO 8601 UTC with three fractional digits.
PRD §2.6: monetary fields ending in `_cents` are integer whole cents.
"""
from __future__ import annotations

import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Time helpers — PRD §2.6 ISO 8601 UTC with three fractional digits.
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


def add_seconds(iso_ts: str, seconds: float) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(seconds=seconds))


def add_minutes(iso_ts: str, minutes: float) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(minutes=minutes))


def add_hours(iso_ts: str, hours: float) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(hours=hours))


def add_days(iso_ts: str, days: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(days=days))


# ---------------------------------------------------------------------------
# Random suffix — for cross-test uniqueness.
# ---------------------------------------------------------------------------
def random_suffix(n: int = 8) -> str:
    return "".join(
        random.choices(string.ascii_lowercase + string.digits, k=n)
    )


def unique_idempotency_key(prefix: str = "k") -> str:
    """Generate a unique idempotency key.

    PRD §3.5: "an `idempotency_key` of 1 to 64 characters that is
    unique within `shift_id`".
    """
    return f"{prefix}-{random_suffix(10)}"


# ---------------------------------------------------------------------------
# Employee — POST /timekeeping/employees
# PRD §3.1
# ---------------------------------------------------------------------------
def create_employee_payload(
    *,
    full_name: Optional[str] = None,
    jurisdiction: str = "FED",
    classification: str = "NON_EXEMPT",
    base_hourly_rate_cents: Optional[int] = None,
    tipped_role: Optional[bool] = None,
    tipped_cash_rate_cents: Optional[int] = None,
    applicable_minimum_wage_cents: Optional[int] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Build a POST /timekeeping/employees payload.

    Defaults to NON_EXEMPT / FED with base rate 2000 cents. The PRD
    requires `base_hourly_rate_cents` when classification is NON_EXEMPT;
    we always include it for NON_EXEMPT defaults, and omit it for EXEMPT.
    Tipped fields are added only when `tipped_role=True`, per the PRD
    rule that non-tipped employees must NOT supply tipped fields
    (`ERR_TIPPED_FIELDS_MISMATCH`).
    """
    payload: Dict[str, Any] = {
        "full_name": full_name or TEST_DEFAULTS["EMPLOYEE_FULL_NAME"],
        "jurisdiction": jurisdiction,
        "classification": classification,
    }
    if classification == "NON_EXEMPT":
        payload["base_hourly_rate_cents"] = (
            base_hourly_rate_cents
            if base_hourly_rate_cents is not None
            else TEST_DEFAULTS["BASE_HOURLY_RATE_CENTS"]
        )
    elif base_hourly_rate_cents is not None:
        # Explicit override is honored even when EXEMPT, in case a test
        # needs to probe field handling.
        payload["base_hourly_rate_cents"] = base_hourly_rate_cents
    if tipped_role is not None:
        payload["tipped_role"] = tipped_role
        if tipped_role is True:
            payload["tipped_cash_rate_cents"] = (
                tipped_cash_rate_cents
                if tipped_cash_rate_cents is not None
                else TEST_DEFAULTS["TIPPED_CASH_RATE_CENTS"]
            )
            payload["applicable_minimum_wage_cents"] = (
                applicable_minimum_wage_cents
                if applicable_minimum_wage_cents is not None
                else TEST_DEFAULTS["APPLICABLE_MINIMUM_WAGE_CENTS"]
            )
        else:
            # Allow explicit overrides even when tipped_role=False —
            # needed for the ERR_TIPPED_FIELDS_MISMATCH probe.
            if tipped_cash_rate_cents is not None:
                payload["tipped_cash_rate_cents"] = tipped_cash_rate_cents
            if applicable_minimum_wage_cents is not None:
                payload["applicable_minimum_wage_cents"] = (
                    applicable_minimum_wage_cents
                )
    payload.update(extra)
    return payload


def update_employee_payload(
    *,
    version: Optional[int] = None,
    classification: Optional[str] = None,
    base_hourly_rate_cents: Optional[int] = None,
    jurisdiction: Optional[str] = None,
    tipped_role: Optional[bool] = None,
    tipped_cash_rate_cents: Optional[int] = None,
    applicable_minimum_wage_cents: Optional[int] = None,
    status: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Build a PATCH /timekeeping/employees/{id} payload."""
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    if classification is not None:
        payload["classification"] = classification
    if base_hourly_rate_cents is not None:
        payload["base_hourly_rate_cents"] = base_hourly_rate_cents
    if jurisdiction is not None:
        payload["jurisdiction"] = jurisdiction
    if tipped_role is not None:
        payload["tipped_role"] = tipped_role
    if tipped_cash_rate_cents is not None:
        payload["tipped_cash_rate_cents"] = tipped_cash_rate_cents
    if applicable_minimum_wage_cents is not None:
        payload["applicable_minimum_wage_cents"] = (
            applicable_minimum_wage_cents
        )
    if status is not None:
        payload["status"] = status
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Shift — POST /timekeeping/shifts
# PRD §3.2: required input is employee_id, scheduled_start, scheduled_end.
# ---------------------------------------------------------------------------
def create_shift_payload(
    employee_id: str,
    *,
    scheduled_start: Optional[str] = None,
    scheduled_end: Optional[str] = None,
    duration_hours: float = 8.0,
    **extra: Any,
) -> Dict[str, Any]:
    """Build a POST /timekeeping/shifts payload.

    If only one of `scheduled_start` / `scheduled_end` is provided, the
    other is derived using `duration_hours`. If neither is provided,
    the shift defaults to MONDAY 08:00 → 16:00 on the anchor week.
    """
    if scheduled_start is None and scheduled_end is None:
        scheduled_start = TEST_DEFAULTS["MONDAY_0800"]
        scheduled_end = TEST_DEFAULTS["MONDAY_1600"]
    elif scheduled_end is None:
        scheduled_end = add_hours(scheduled_start, duration_hours)
    elif scheduled_start is None:
        scheduled_start = add_hours(scheduled_end, -duration_hours)
    payload: Dict[str, Any] = {
        "employee_id": employee_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Punch — POST /timekeeping/shifts/{id}/punches
# PRD §3.2: input is punch_type only. The server stamps `punched_at`.
# ---------------------------------------------------------------------------
def create_punch_payload(
    punch_type: str = "IN",
    **extra: Any,
) -> Dict[str, Any]:
    """Build a POST /timekeeping/shifts/{id}/punches payload.

    PRD §3.2: "The server stamps `punched_at` at the moment of request
    receipt and never accepts a caller-supplied value for it".
    """
    payload: Dict[str, Any] = {"punch_type": punch_type}
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# TimeEdit — POST /timekeeping/time-edits
# PRD §3.5
# ---------------------------------------------------------------------------
def create_time_edit_payload(
    *,
    shift_id: str,
    target_punch_id: str,
    proposed_punched_at: str,
    reason_code: str = "CLERICAL",
    idempotency_key: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Build a POST /timekeeping/time-edits payload.

    PRD §3.5: required input fields are shift_id, target_punch_id,
    proposed_punched_at, reason_code, idempotency_key.
    """
    payload: Dict[str, Any] = {
        "shift_id": shift_id,
        "target_punch_id": target_punch_id,
        "proposed_punched_at": proposed_punched_at,
        "reason_code": reason_code,
        "idempotency_key": idempotency_key or unique_idempotency_key(),
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# TipDeclaration — POST /timekeeping/shifts/{id}/tip-declaration
# PRD §3.7
# ---------------------------------------------------------------------------
def create_tip_declaration_payload(
    declared_tips_cents: int,
    **extra: Any,
) -> Dict[str, Any]:
    """Build a POST /timekeeping/shifts/{id}/tip-declaration payload.

    PRD §3.7: required input is `declared_tips_cents` (>= 0).
    """
    payload: Dict[str, Any] = {
        "declared_tips_cents": declared_tips_cents,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Workweek lock — POST /timekeeping/workweeks/{id}/lock
# No body required; passing None to api_client.lock_workweek.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Test clock — PRD §3.8
# ---------------------------------------------------------------------------
def clock_advance_payload(seconds: int) -> Dict[str, Any]:
    """Build a POST /timekeeping/_clock/advance payload.

    PRD §3.8: "A clock-advance capability accepts an integer `seconds`
    field and shifts the server's logical now by that many seconds".
    """
    return {"seconds": int(seconds)}


def clock_set_payload(now: str) -> Dict[str, Any]:
    """Build a POST /timekeeping/_clock/set payload.

    PRD §3.8: "a clock-set capability accepts an ISO 8601 timestamp
    `now` and sets the server's logical now to that instant".
    """
    return {"now": now}


__all__ = [
    "iso_utc", "utcnow", "iso_now",
    "parse_iso",
    "add_seconds", "add_minutes", "add_hours", "add_days",
    "random_suffix",
    "unique_idempotency_key",
    "create_employee_payload",
    "update_employee_payload",
    "create_shift_payload",
    "create_punch_payload",
    "create_time_edit_payload",
    "create_tip_declaration_payload",
    "clock_advance_payload",
    "clock_set_payload",
]
