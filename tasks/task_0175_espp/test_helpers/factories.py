"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the JSON body shape the PRD declares for the
request (PRD §3 narratives + §4 endpoint table). Tests pass overrides
for the values they want to control. Only PRD-declared input fields are
produced; computed / system fields are intentionally omitted.

PRD §2.7: monetary amounts are integer cents; share counts are integer
whole shares; rates are basis points with denominator 10_000.
PRD §2.9: timestamps are ISO 8601 UTC with three fractional digits.
"""
from __future__ import annotations

import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Time helpers — PRD §2.9 ISO 8601 UTC with three fractional digits.
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


def parse_iso(iso_ts: str) -> datetime:
    """Parse an ISO 8601 string accepting both 'Z' and '+00:00'."""
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


def add_seconds(iso_ts: str, seconds: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(seconds=seconds))


def add_minutes(iso_ts: str, minutes: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(minutes=minutes))


def add_days(iso_ts: str, days: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(days=days))


def add_months(iso_ts: str, months: int) -> str:
    """Add `months` calendar months to an ISO timestamp.

    PRD §3.1: "`end_date` is computed as `start_date` plus
    `offering_period_months` months". This helper mirrors that
    arithmetic for use in test fixtures that need to know op end dates
    or the day after.
    """
    dt = parse_iso(iso_ts)
    total = dt.month - 1 + months
    new_year = dt.year + total // 12
    new_month = total % 12 + 1
    # day-of-month clamping: keep the day if valid, else the last day of
    # the target month. None of our scenarios use day > 28.
    day = min(dt.day, _last_day_of_month(new_year, new_month))
    new_dt = dt.replace(year=new_year, month=new_month, day=day)
    return iso_utc(new_dt)


def _last_day_of_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    next_first = date(year, month + 1, 1)
    return (next_first - timedelta(days=1)).day


def add_years(iso_ts: str, years: int) -> str:
    dt = parse_iso(iso_ts)
    try:
        new_dt = dt.replace(year=dt.year + years)
    except ValueError:
        # Feb 29 -> Feb 28 on non-leap.
        new_dt = dt.replace(year=dt.year + years, day=28)
    return iso_utc(new_dt)


def date_only_iso(year: int, month: int, day: int) -> str:
    """Render a calendar date as an ISO 8601 instant at midnight UTC."""
    return iso_utc(datetime(year, month, day, tzinfo=timezone.utc))


# ---------------------------------------------------------------------------
# Random suffix — cross-test uniqueness.
# ---------------------------------------------------------------------------
def random_suffix(n: int = 8) -> str:
    return "".join(
        random.choices(string.ascii_lowercase + string.digits, k=n)
    )


def unique_plan_name(prefix: str = "Plan") -> str:
    return f"{prefix}-{random_suffix(10)}"


def unique_operator_id(prefix: str = "op") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Plan — POST /plans (PRD §3.1)
# Required input: name, offering_period_months, effective_date.
# Optional input: max_contribution_rate_bp, annual_accrual_cap_cents,
#                 lookback_enabled, discount_bp.
# ---------------------------------------------------------------------------
def create_plan_payload(
    *,
    name: Optional[str] = None,
    offering_period_months: Optional[int] = None,
    effective_date: Optional[str] = None,
    max_contribution_rate_bp: Optional[int] = None,
    annual_accrual_cap_cents: Optional[int] = None,
    lookback_enabled: Optional[bool] = None,
    discount_bp: Optional[int] = None,
    omit: Optional[list] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name or unique_plan_name(),
        "offering_period_months":
            offering_period_months
            if offering_period_months is not None
            else TEST_DEFAULTS["OFFERING_PERIOD_MONTHS"],
        "effective_date":
            effective_date or TEST_DEFAULTS["PLAN_EFFECTIVE_DATE"],
    }
    if max_contribution_rate_bp is not None:
        payload["max_contribution_rate_bp"] = max_contribution_rate_bp
    if annual_accrual_cap_cents is not None:
        payload["annual_accrual_cap_cents"] = annual_accrual_cap_cents
    if lookback_enabled is not None:
        payload["lookback_enabled"] = lookback_enabled
    if discount_bp is not None:
        payload["discount_bp"] = discount_bp
    if extra:
        payload.update(extra)
    if omit:
        for k in omit:
            payload.pop(k, None)
    return payload


def update_plan_payload(
    *,
    version: int,
    name: Optional[str] = None,
    offering_period_months: Optional[int] = None,
    effective_date: Optional[str] = None,
    max_contribution_rate_bp: Optional[int] = None,
    annual_accrual_cap_cents: Optional[int] = None,
    lookback_enabled: Optional[bool] = None,
    discount_bp: Optional[int] = None,
) -> Dict[str, Any]:
    """PATCH /plans/{id} — partial body, OCC via version (PRD §2.10)."""
    payload: Dict[str, Any] = {"version": version}
    if name is not None:
        payload["name"] = name
    if offering_period_months is not None:
        payload["offering_period_months"] = offering_period_months
    if effective_date is not None:
        payload["effective_date"] = effective_date
    if max_contribution_rate_bp is not None:
        payload["max_contribution_rate_bp"] = max_contribution_rate_bp
    if annual_accrual_cap_cents is not None:
        payload["annual_accrual_cap_cents"] = annual_accrual_cap_cents
    if lookback_enabled is not None:
        payload["lookback_enabled"] = lookback_enabled
    if discount_bp is not None:
        payload["discount_bp"] = discount_bp
    return payload


# ---------------------------------------------------------------------------
# OfferingPeriod FMV writes — PRD §3.2
# ---------------------------------------------------------------------------
def grant_fmv_payload(*, grant_date_fmv_cents: int) -> Dict[str, Any]:
    return {"grant_date_fmv_cents": grant_date_fmv_cents}


def purchase_fmv_payload(
    *,
    purchase_date_fmv_cents: int,
    version: int,
) -> Dict[str, Any]:
    """PATCH /offering-periods/{id}/fmv — OCC version mandatory in
    scaffold input list. PRD §2.10 says version is optional; we include
    it by default and let callers omit by setting `version=None` upstream.
    """
    return {
        "purchase_date_fmv_cents": purchase_date_fmv_cents,
        "version": version,
    }


def purchase_fmv_payload_no_version(
    *, purchase_date_fmv_cents: int,
) -> Dict[str, Any]:
    """Variant without `version` — for tests that probe the optional
    nature of OCC per PRD §2.10."""
    return {"purchase_date_fmv_cents": purchase_date_fmv_cents}


# ---------------------------------------------------------------------------
# Enrollment — POST/PATCH (PRD §3.3)
# ---------------------------------------------------------------------------
def create_enrollment_payload(*, contribution_rate_bp: int) -> Dict[str, Any]:
    return {"contribution_rate_bp": contribution_rate_bp}


def update_enrollment_payload(
    *,
    contribution_rate_bp: int,
    version: int,
) -> Dict[str, Any]:
    return {
        "contribution_rate_bp": contribution_rate_bp,
        "version": version,
    }


# ---------------------------------------------------------------------------
# Contribution — POST (PRD §3.4)
# ---------------------------------------------------------------------------
def create_contribution_payload(
    *,
    pay_period_end: str,
    gross_pay_cents: int,
) -> Dict[str, Any]:
    return {
        "pay_period_end": pay_period_end,
        "gross_pay_cents": gross_pay_cents,
    }


# ---------------------------------------------------------------------------
# Disposition — POST/PATCH (PRD §3.7)
# ---------------------------------------------------------------------------
def create_disposition_payload(
    *,
    purchase_id: str,
    disposition_date: str,
    shares_disposed: int,
    sale_price_per_share_cents: int,
) -> Dict[str, Any]:
    return {
        "purchase_id": purchase_id,
        "disposition_date": disposition_date,
        "shares_disposed": shares_disposed,
        "sale_price_per_share_cents": sale_price_per_share_cents,
    }


def update_disposition_payload(
    *,
    version: int,
    disposition_date: Optional[str] = None,
    shares_disposed: Optional[int] = None,
    sale_price_per_share_cents: Optional[int] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"version": version}
    if disposition_date is not None:
        payload["disposition_date"] = disposition_date
    if shares_disposed is not None:
        payload["shares_disposed"] = shares_disposed
    if sale_price_per_share_cents is not None:
        payload["sale_price_per_share_cents"] = sale_price_per_share_cents
    return payload


# ---------------------------------------------------------------------------
# Clock advance — POST /_clock/advance (PRD §2.9)
# ---------------------------------------------------------------------------
def clock_advance_payload(*, to_timestamp: str) -> Dict[str, Any]:
    return {"to_timestamp": to_timestamp}


__all__ = [
    # Time helpers
    "iso_utc", "utcnow", "parse_iso",
    "add_seconds", "add_minutes", "add_days",
    "add_months", "add_years", "date_only_iso",
    # Uniqueness
    "random_suffix", "unique_plan_name", "unique_operator_id",
    # Payload factories
    "create_plan_payload",
    "update_plan_payload",
    "grant_fmv_payload",
    "purchase_fmv_payload",
    "purchase_fmv_payload_no_version",
    "create_enrollment_payload",
    "update_enrollment_payload",
    "create_contribution_payload",
    "create_disposition_payload",
    "update_disposition_payload",
    "clock_advance_payload",
]
