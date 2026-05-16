"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body. Tests pass overrides for the values they want to control.
Only PRD-declared input fields are produced; computed/system fields are
intentionally omitted so the implementation cannot accidentally accept
them as inputs.

PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
PRD §2.7: monetary fields are integer cents.
"""
from __future__ import annotations

import random
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

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
    """Parse an ISO 8601 UTC timestamp back into a datetime."""
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# ISO date helpers — for date-only fields (event_date, effective_date,
# date_of_birth, coverage_start_date, billing_month, due_date,
# window_opens_on/closes_on).
# ---------------------------------------------------------------------------
def iso_date(d: date) -> str:
    return d.isoformat()


def date_today_utc() -> date:
    return datetime.now(tz=timezone.utc).date()


def date_offset(*, days: int = 0, base: Optional[date] = None) -> date:
    base = base or date_today_utc()
    return base + timedelta(days=days)


def dob_for_age(target_age: int, reference: Optional[date] = None) -> str:
    """Compute date_of_birth (YYYY-MM-DD) such that the member is roughly
    `target_age` whole years old on `reference`.

    Used for: HouseholdMember.date_of_birth (PRD §3.1), enrollment age
    math (PRD §3.6), Medicaid age thresholds (PRD §3.3).
    """
    reference = reference or date_today_utc()
    # Use 365 days/year + 30-day cushion so the age is stable.
    days_back = target_age * 365 + 30
    return iso_date(reference - timedelta(days=days_back))


def first_of_month(year: int, month: int) -> str:
    return iso_date(date(year, month, 1))


def last_of_month(year: int, month: int) -> str:
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    return iso_date(nxt - timedelta(days=1))


_ALPHANUM = string.ascii_uppercase + string.digits


def random_suffix(n: int = 8) -> str:
    return "".join(random.choices(_ALPHANUM, k=n))


def random_uuid() -> str:
    return str(uuid.uuid4())


# ===========================================================================
# Application — PRD §3.1
# ===========================================================================
def create_application_payload(
    *,
    coverage_year: int = 2026,
    filing_state: str = "CA",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /applications.

    PRD §3.1: "An applicant begins by creating an application, supplying
    the coverage_year for which coverage is sought and the two-letter
    filing_state where the household resides."
    """
    payload: Dict[str, Any] = {
        "coverage_year": coverage_year,
        "filing_state": filing_state,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# HouseholdMember — PRD §3.1
# ===========================================================================
def create_household_member_payload(
    *,
    filer_type: str = "PRIMARY_FILER",
    date_of_birth: Optional[str] = None,
    age_years: Optional[int] = None,
    reference_date: Optional[date] = None,
    include_in_household: Optional[bool] = None,
    include_in_magi: Optional[bool] = None,
    is_tobacco_user: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /applications/{id}/household-members.

    PRD §3.1: input fields are filer_type (one of PRIMARY_FILER, SPOUSE,
    DEPENDENT), date_of_birth (ISO 8601 calendar date), and three
    optional booleans include_in_household (default true),
    include_in_magi (default true), is_tobacco_user (default false).
    """
    if date_of_birth is None:
        age = age_years if age_years is not None else 35
        date_of_birth = dob_for_age(age, reference=reference_date)
    payload: Dict[str, Any] = {
        "filer_type": filer_type,
        "date_of_birth": date_of_birth,
    }
    if include_in_household is not None:
        payload["include_in_household"] = include_in_household
    if include_in_magi is not None:
        payload["include_in_magi"] = include_in_magi
    if is_tobacco_user is not None:
        payload["is_tobacco_user"] = is_tobacco_user
    payload.update(overrides)
    return payload


def patch_household_member_payload(
    *,
    version: Optional[int] = None,
    include_in_household: Optional[bool] = None,
    include_in_magi: Optional[bool] = None,
    is_tobacco_user: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PATCH /applications/{id}/household-members/{member_id}.

    PRD §2.6: when the caller supplies version, the server compares to
    stored version. Optional fields are updates.
    """
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    if include_in_household is not None:
        payload["include_in_household"] = include_in_household
    if include_in_magi is not None:
        payload["include_in_magi"] = include_in_magi
    if is_tobacco_user is not None:
        payload["is_tobacco_user"] = is_tobacco_user
    payload.update(overrides)
    return payload


# ===========================================================================
# IncomeRecord — PRD §3.1
# ===========================================================================
def create_income_record_payload(
    *,
    source_type: str = "WAGES",
    amount_cents: int = 2_500_000,
    effective_date: Optional[str] = None,
    supersedes_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /applications/{id}/household-members/{member_id}/income-records.

    PRD §3.1: input fields are source_type, amount_cents (may be
    negative), effective_date. Optional supersedes_id input points to a
    prior record being corrected.
    """
    if effective_date is None:
        effective_date = iso_date(date(2026, 1, 1))
    payload: Dict[str, Any] = {
        "source_type": source_type,
        "amount_cents": amount_cents,
        "effective_date": effective_date,
    }
    if supersedes_id is not None:
        payload["supersedes_id"] = supersedes_id
    payload.update(overrides)
    return payload


# ===========================================================================
# SEPEvent — PRD §3.4
# ===========================================================================
def create_sep_event_payload(
    *,
    event_type: str = "MARRIAGE",
    event_date: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /applications/{id}/sep-events.

    PRD §3.4: input fields are event_type (one of LOSS_OF_COVERAGE,
    MARRIAGE, BIRTH_ADOPTION, MOVE, INCOME_CHANGE, MEDICAID_LOSS,
    GAINED_CITIZENSHIP) and event_date (ISO 8601 calendar date).
    """
    if event_date is None:
        event_date = iso_date(date_today_utc())
    payload: Dict[str, Any] = {
        "event_type": event_type,
        "event_date": event_date,
    }
    payload.update(overrides)
    return payload


def deny_application_payload(*, reason: Optional[str] = None,
                             **overrides: Any) -> Dict[str, Any]:
    """POST /applications/{id}/deny. PRD §3.3: "Denial accepts an
    optional reason to be recorded for audit purposes."
    """
    payload: Dict[str, Any] = {}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


def reject_sep_event_payload(*, reason: Optional[str] = None,
                             **overrides: Any) -> Dict[str, Any]:
    """POST /applications/{app_id}/sep-events/{id}/reject. PRD §3.4:
    "Rejection records an optional reason."
    """
    payload: Dict[str, Any] = {}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


# ===========================================================================
# Insurer — PRD §3.5
# ===========================================================================
def create_insurer_payload(
    *,
    name: Optional[str] = None,
    filing_states: Optional[List[str]] = None,
    contact_phone: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /insurers.

    PRD §3.5: input fields are name, filing_states (list of two-letter
    state codes), contact_phone.
    """
    payload: Dict[str, Any] = {
        "name": name or f"Insurer {random_suffix(4)}",
        "filing_states": filing_states or ["CA"],
        "contact_phone": contact_phone or "+18005551212",
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# Plan — PRD §3.5
# ===========================================================================
def create_plan_payload(
    *,
    insurer_id: str,
    coverage_year: int = 2026,
    filing_state: str = "CA",
    tier: str = "SILVER",
    base_monthly_premium_cents: int = 40_000,
    is_benchmark_silver: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /plans.

    PRD §3.5: input fields are insurer_id, coverage_year, filing_state
    (must be in insurer.filing_states), tier (BRONZE/SILVER/GOLD/
    PLATINUM), base_monthly_premium_cents, optional is_benchmark_silver
    (default false).
    """
    payload: Dict[str, Any] = {
        "insurer_id": insurer_id,
        "coverage_year": coverage_year,
        "filing_state": filing_state,
        "tier": tier,
        "base_monthly_premium_cents": base_monthly_premium_cents,
    }
    if is_benchmark_silver is not None:
        payload["is_benchmark_silver"] = is_benchmark_silver
    payload.update(overrides)
    return payload


def patch_plan_payload(
    *,
    version: Optional[int] = None,
    base_monthly_premium_cents: Optional[int] = None,
    status: Optional[str] = None,
    is_benchmark_silver: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PATCH /plans/{id}.

    PRD §2.6: when version is supplied, server compares to stored
    version. Optional fields are updates.
    """
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    if base_monthly_premium_cents is not None:
        payload["base_monthly_premium_cents"] = base_monthly_premium_cents
    if status is not None:
        payload["status"] = status
    if is_benchmark_silver is not None:
        payload["is_benchmark_silver"] = is_benchmark_silver
    payload.update(overrides)
    return payload


# ===========================================================================
# PlanVariant — PRD §3.5
# ===========================================================================
def create_plan_variant_payload(
    *,
    csr_level: str = "STANDARD",
    actuarial_value: float = 70.0,
    out_of_pocket_max_cents: int = 900_000,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /plans/{id}/variants.

    PRD §3.5: input fields are csr_level (STANDARD/CSR_73/CSR_87/CSR_94/
    CSR_PLUS), actuarial_value (e.g., 73 for CSR_73),
    out_of_pocket_max_cents.
    """
    payload: Dict[str, Any] = {
        "csr_level": csr_level,
        "actuarial_value": actuarial_value,
        "out_of_pocket_max_cents": out_of_pocket_max_cents,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# Enrollment — PRD §3.6
# ===========================================================================
def create_enrollment_payload(
    *,
    application_id: str,
    plan_variant_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /enrollments.

    PRD §3.6: input fields are application_id and plan_variant_id.
    """
    payload: Dict[str, Any] = {
        "application_id": application_id,
        "plan_variant_id": plan_variant_id,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# PremiumInvoice — PRD §3.7
# ===========================================================================
def post_payment_payload(*, amount_cents: int,
                         **overrides: Any) -> Dict[str, Any]:
    """POST /premium-invoices/{id}/post-payment.

    PRD §3.7: input is amount_cents (must be >= invoice.net_amount_cents).
    """
    payload: Dict[str, Any] = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def waive_invoice_payload(*, reason: Optional[str] = None,
                          **overrides: Any) -> Dict[str, Any]:
    """POST /premium-invoices/{id}/waive. PRD §3.7: optional reason."""
    payload: Dict[str, Any] = {}
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


# ===========================================================================
# Clock + sweeps — PRD §2.9 / §3.8
# ===========================================================================
def clock_advance_payload(*, to_timestamp: str,
                          **overrides: Any) -> Dict[str, Any]:
    """POST /_clock/advance. PRD §2.9: required input is to_timestamp."""
    payload: Dict[str, Any] = {"to_timestamp": to_timestamp}
    payload.update(overrides)
    return payload


def reconcile_aptc_payload(*, coverage_year: int,
                           **overrides: Any) -> Dict[str, Any]:
    """POST /_sweep/reconcile-aptc. PRD §3.8: required input is
    coverage_year.
    """
    payload: Dict[str, Any] = {"coverage_year": coverage_year}
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
    "dob_for_age",
    "first_of_month",
    "last_of_month",
    "random_suffix",
    "random_uuid",
    "create_application_payload",
    "create_household_member_payload",
    "patch_household_member_payload",
    "create_income_record_payload",
    "create_sep_event_payload",
    "deny_application_payload",
    "reject_sep_event_payload",
    "create_insurer_payload",
    "create_plan_payload",
    "patch_plan_payload",
    "create_plan_variant_payload",
    "create_enrollment_payload",
    "post_payment_payload",
    "waive_invoice_payload",
    "clock_advance_payload",
    "reconcile_aptc_payload",
]
