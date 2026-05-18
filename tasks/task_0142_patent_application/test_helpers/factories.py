"""Payload factories — one per endpoint that accepts a body. Only
source: input fields are emitted; computed fields (status, filed_at,
granted_at, expires_at, total_fees_paid_cents, action_number,
issued_at, response_deadline_at, extended_deadline_at, window_open_at,
due_at, grace_period_end_at, required_fee_cents, priority_date,
national_phase_deadline_at, national_entered_at, applicant_risk_score,
months_extension, extension_fee_cents) are computed by the server.

Fee computation helpers also live here so both factories and fixtures
can reach the exact integer-cent amount the server expects per PRD
§2.7 and §3.2 / §3.3 / §3.5 / §3.6.
"""
from __future__ import annotations

import math
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Optional

from .constants import (
    ENTITY_MULTIPLIER,
    EXAMINATION_FEE_BASE_CENTS,
    EXCESS_INDEP_CLAIM_THRESHOLD,
    EXCESS_INDEP_CLAIM_UNIT_CENTS,
    EXCESS_TOTAL_CLAIM_THRESHOLD,
    EXCESS_TOTAL_CLAIM_UNIT_CENTS,
    EXTENSION_FEE_TABLE_CENTS,
    EXTENSION_MAX_MONTHS,
    FILING_FEE_TABLE_CENTS,
    ISSUE_FEE_BASE_CENTS,
    MAINTENANCE_FEE_TABLE_CENTS,
    MAINTENANCE_SURCHARGE_CENTS,
    PCT_NATIONAL_BASE_CENTS,
)


# ---------------------------------------------------------------------------
# Identifiers / random helpers
# ---------------------------------------------------------------------------
def _suffix(n: int = 6) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def iso_utc(dt: datetime) -> str:
    """Format a datetime as PRD §2.2-style ISO 8601 UTC with three
    fractional digits, ending in Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def utc(year: int, month: int, day: int,
        hour: int = 0, minute: int = 0, second: int = 0, ms: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, second, ms * 1000, tzinfo=timezone.utc)


# A stable anchor — early enough that 11.5 years still falls in a clean
# decade.
DEFAULT_BASE_CLOCK = utc(2024, 1, 1, 0, 0, 0)


# ---------------------------------------------------------------------------
# Fee math — PRD §2.7 round-half-up to integer cents.
# ---------------------------------------------------------------------------
def round_half_up_cents(value: float) -> int:
    """PRD §2.7: integer USD cents, round-half-up."""
    q = Decimal(repr(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def filing_fee_cents(application_type: str, entity_size: str) -> int:
    """PRD §3.2 filing fee: base * multiplier, round-half-up, single
    step."""
    base = FILING_FEE_TABLE_CENTS[application_type]
    mult = ENTITY_MULTIPLIER[entity_size]
    return round_half_up_cents(base * mult)


def examination_fee_cents(entity_size: str) -> int:
    """PRD §3.3 examination fee: base * multiplier, round-half-up.
    The PRD prose names the fee but its base value is reserved to the
    fee schedule; implementations and tests share the same base value
    so that fixtures can reach UNDER_EXAMINATION deterministically.
    """
    base = EXAMINATION_FEE_BASE_CENTS
    mult = ENTITY_MULTIPLIER[entity_size]
    return round_half_up_cents(base * mult)


def issue_fee_cents(entity_size: str) -> int:
    """PRD §3.4 issue fee: base * multiplier, round-half-up."""
    base = ISSUE_FEE_BASE_CENTS
    mult = ENTITY_MULTIPLIER[entity_size]
    return round_half_up_cents(base * mult)


def excess_claim_fee_cents(
    claim_count: int, independent_claim_count: int, entity_size: str,
) -> int:
    """PRD §3.2 excess-claim fee — pinned order: round per-component
    THEN sum.

    "The two components are computed independently in a pinned order:
    first the excess-total component multiplies the unit price by the
    count and by the entity multiplier and rounds half-up; then the
    excess-independent component multiplies the unit price by the count
    and by the entity multiplier and rounds half-up; and only then are
    the two rounded integer components summed".
    """
    excess_total = max(0, claim_count - EXCESS_TOTAL_CLAIM_THRESHOLD)
    excess_indep = max(0, independent_claim_count - EXCESS_INDEP_CLAIM_THRESHOLD)
    mult = ENTITY_MULTIPLIER[entity_size]
    total_part = round_half_up_cents(excess_total * EXCESS_TOTAL_CLAIM_UNIT_CENTS * mult)
    indep_part = round_half_up_cents(excess_indep * EXCESS_INDEP_CLAIM_UNIT_CENTS * mult)
    return total_part + indep_part


def needs_excess_claim_fee(claim_count: int, independent_claim_count: int) -> bool:
    """PRD §3.2: an additional EXCESS_CLAIM fee is required when
    claim_count > 20 OR independent_claim_count > 3."""
    return (
        claim_count > EXCESS_TOTAL_CLAIM_THRESHOLD
        or independent_claim_count > EXCESS_INDEP_CLAIM_THRESHOLD
    )


def extension_fee_cents(months_extension: int, entity_size: str) -> int:
    """PRD §3.3 extension fee: base * multiplier, round-half-up.
    Months in {1, 2, 3}. Zero months => zero. Returns the integer-cent
    amount the extension FeeTransaction must carry."""
    if months_extension == 0:
        return 0
    if not (1 <= months_extension <= EXTENSION_MAX_MONTHS):
        raise ValueError(f"months_extension out of range: {months_extension}")
    base = EXTENSION_FEE_TABLE_CENTS[months_extension]
    mult = ENTITY_MULTIPLIER[entity_size]
    return round_half_up_cents(base * mult)


def maintenance_fee_cents(stage: str, entity_size: str, in_grace: bool) -> int:
    """PRD §3.5 maintenance fee: round(base * multiplier) + surcharge
    (flat, only when in_grace).

    "first multiply the base fee by the applicant's entity multiplier
    from §2.7 and round half-up to integer cents; then add the flat
    surcharge if the grace condition is met. The surcharge itself is
    not subject to the entity multiplier".
    """
    base = MAINTENANCE_FEE_TABLE_CENTS[stage]
    mult = ENTITY_MULTIPLIER[entity_size]
    rounded = round_half_up_cents(base * mult)
    if in_grace:
        rounded += MAINTENANCE_SURCHARGE_CENTS
    return rounded


def pct_national_fee_cents(entity_size: str) -> int:
    """PRD §3.6 PCT national-entry fee: 51000 * multiplier,
    round-half-up."""
    mult = ENTITY_MULTIPLIER[entity_size]
    return round_half_up_cents(PCT_NATIONAL_BASE_CENTS * mult)


# ---------------------------------------------------------------------------
# Applicant (PRD §3.1)
# ---------------------------------------------------------------------------
def create_applicant_payload(
    name: Optional[str] = None,
    entity_size: str = "SMALL",
    gross_income_cents: Optional[int] = None,
    prior_filings_count: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "name": name or f"Applicant-{_suffix()}",
        "entity_size": entity_size,
    }
    if gross_income_cents is not None:
        defaults["gross_income_cents"] = gross_income_cents
    if prior_filings_count is not None:
        defaults["prior_filings_count"] = prior_filings_count
    defaults.update(overrides)
    return defaults


def patch_applicant_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.1 PATCH /applicants/{id}: name?, entity_size?,
    gross_income_cents?, prior_filings_count?, version?."""
    return dict(overrides)


# ---------------------------------------------------------------------------
# Application (PRD §3.2)
# ---------------------------------------------------------------------------
def create_application_payload(
    applicant_id: str,
    application_type: str = "UTILITY",
    title: Optional[str] = None,
    claim_count: int = 1,
    independent_claim_count: int = 1,
    parent_application_id: Optional[str] = None,
    continuation_type: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "applicant_id": applicant_id,
        "application_type": application_type,
        "title": title or f"Invention-{_suffix()}",
        "claim_count": claim_count,
        "independent_claim_count": independent_claim_count,
    }
    if parent_application_id is not None:
        defaults["parent_application_id"] = parent_application_id
    if continuation_type is not None:
        defaults["continuation_type"] = continuation_type
    defaults.update(overrides)
    return defaults


def patch_application_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.2 PATCH /applications/{id}: title?, claim_count?,
    independent_claim_count?, version?."""
    return dict(overrides)


# ---------------------------------------------------------------------------
# Fees (PRD §3.2 etc.)
# ---------------------------------------------------------------------------
def create_fee_payload(
    fee_category: str,
    amount_cents: int,
    maintenance_fee_id: Optional[str] = None,
    office_action_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "fee_category": fee_category,
        "amount_cents": amount_cents,
    }
    if maintenance_fee_id is not None:
        payload["maintenance_fee_id"] = maintenance_fee_id
    if office_action_id is not None:
        payload["office_action_id"] = office_action_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Office Action (PRD §3.3)
# ---------------------------------------------------------------------------
def create_office_action_payload(action_type: str = "NON_FINAL", **overrides) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action_type": action_type}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock advance (PRD §2.8 / §4)
# ---------------------------------------------------------------------------
def advance_clock_payload(to_iso: str) -> Dict[str, Any]:
    return {"to": to_iso}


# ---------------------------------------------------------------------------
# Date utilities
# ---------------------------------------------------------------------------
def add_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)


def add_years_approx(dt: datetime, years: float) -> datetime:
    """Approximate forward year-shift using 365.25 days per year for
    test convenience. Production server math may anchor on calendar
    arithmetic; PRD §3.4 datetime precision is to the second, so tests
    compute reference dates approximately and use server-returned
    timestamps as the source of truth for boundary-precision tests."""
    return dt + timedelta(days=round(years * 365.25))


def add_calendar_years(dt: datetime, years: int) -> datetime:
    """Add years using calendar (Feb 29 handling: roll back to Feb 28)."""
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        return dt.replace(year=dt.year + years, day=28)


__all__ = [
    "iso_utc",
    "utc",
    "DEFAULT_BASE_CLOCK",
    "round_half_up_cents",
    "filing_fee_cents",
    "examination_fee_cents",
    "issue_fee_cents",
    "excess_claim_fee_cents",
    "needs_excess_claim_fee",
    "extension_fee_cents",
    "maintenance_fee_cents",
    "pct_national_fee_cents",
    "create_applicant_payload",
    "patch_applicant_payload",
    "create_application_payload",
    "patch_application_payload",
    "create_fee_payload",
    "create_office_action_payload",
    "advance_clock_payload",
    "add_days",
    "add_years_approx",
    "add_calendar_years",
]
