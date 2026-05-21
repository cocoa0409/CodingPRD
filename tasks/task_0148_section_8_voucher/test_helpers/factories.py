"""Payload factories — one per endpoint that accepts a body, input
fields only (PRD §3, §4).

PRD §2.6: "All monetary values cross the API as integer cents."
PRD §2.7: "All ... derived deadline fields ... read from this clock."
"""
from __future__ import annotations

import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Time helpers — PRD §2.6, §2.7
# ---------------------------------------------------------------------------
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime) -> str:
    """ISO 8601 UTC with milliseconds — PRD §2.4: '... ISO 8601 UTC
    timestamp with three fractional digits'."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_now() -> str:
    return iso_utc(utcnow())


def iso_instant_utc(dt: datetime) -> str:
    return iso_utc(dt)


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 string back to a UTC-aware datetime."""
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)


def add_seconds(dt: datetime, seconds: int) -> datetime:
    return dt + timedelta(seconds=seconds)


def add_hours(dt: datetime, hours: int) -> datetime:
    return dt + timedelta(hours=hours)


# ---------------------------------------------------------------------------
# Random helpers — used to keep test entities mutually distinct.
# ---------------------------------------------------------------------------
def random_suffix(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def random_address() -> str:
    return f"{random.randint(100, 9999)} {random_suffix(6).title()} St"


def random_name(prefix: str = "Household") -> str:
    return f"{prefix}-{random_suffix(6)}"


# ---------------------------------------------------------------------------
# Concurrency envelope — PRD §2.5
# ---------------------------------------------------------------------------
def version_payload(version: Optional[int],
                    base: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    out: Dict[str, Any] = {} if base is None else dict(base)
    if version is not None:
        out["version"] = version
    return out


# ---------------------------------------------------------------------------
# Applicant — POST /applicants — PRD §3.1
# ---------------------------------------------------------------------------
def create_applicant_payload(
    household_name: Optional[str] = None,
    household_size: int = 3,
    dependents_count: int = 1,
    elderly_or_disabled_head: bool = False,
    gross_annual_income_cents: int = 3_000_000,
    childcare_expense_annual_cents: Optional[int] = None,
    medical_expense_annual_cents: Optional[int] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "household_name": household_name or random_name(),
        "household_size": household_size,
        "dependents_count": dependents_count,
        "elderly_or_disabled_head": elderly_or_disabled_head,
        "gross_annual_income_cents": gross_annual_income_cents,
    }
    if childcare_expense_annual_cents is not None:
        payload["childcare_expense_annual_cents"] = childcare_expense_annual_cents
    if medical_expense_annual_cents is not None:
        payload["medical_expense_annual_cents"] = medical_expense_annual_cents
    return payload


# ---------------------------------------------------------------------------
# Voucher — POST /vouchers — PRD §3.2
# ---------------------------------------------------------------------------
def create_voucher_payload(
    applicant_id: str,
    zone: str = "ZONE_A",
    special_mobility_flag: Optional[bool] = None,
    administering_pha_id: str = "PHA_001",
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "applicant_id": applicant_id,
        "zone": zone,
        "administering_pha_id": administering_pha_id,
    }
    if special_mobility_flag is not None:
        payload["special_mobility_flag"] = special_mobility_flag
    return payload


# ---------------------------------------------------------------------------
# Unit — POST /units — PRD §3.3
# ---------------------------------------------------------------------------
def create_unit_payload(
    street_address: Optional[str] = None,
    zone: str = "ZONE_A",
    bedroom_count: int = 2,
    asking_rent_cents: int = 110_000,
    tenant_paid_utilities_cents: Optional[int] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "street_address": street_address or random_address(),
        "zone": zone,
        "bedroom_count": bedroom_count,
        "asking_rent_cents": asking_rent_cents,
    }
    if tenant_paid_utilities_cents is not None:
        payload["tenant_paid_utilities_cents"] = tenant_paid_utilities_cents
    return payload


# ---------------------------------------------------------------------------
# Payment Standard — POST /payment-standards — PRD §3.3
# ---------------------------------------------------------------------------
def create_payment_standard_payload(
    zone: str,
    bedroom_size: int,
    standard_amount_cents: int,
    mobility_amount_cents: Optional[int] = None,
    effective_from: Optional[str] = None,
) -> Dict[str, Any]:
    if mobility_amount_cents is None:
        # PRD §3.3 default: "typically set to 110 percent of it"
        mobility_amount_cents = (standard_amount_cents * 110) // 100
    if effective_from is None:
        # set effective_from well in the past so the row is active now
        effective_from = iso_utc(utcnow() - timedelta(days=3650))
    return {
        "zone": zone,
        "bedroom_size": bedroom_size,
        "standard_amount_cents": standard_amount_cents,
        "mobility_amount_cents": mobility_amount_cents,
        "effective_from": effective_from,
    }


# ---------------------------------------------------------------------------
# Tenancy — POST /tenancies — PRD §3.4
# ---------------------------------------------------------------------------
def create_tenancy_payload(
    voucher_id: str,
    unit_id: str,
    lease_start: str,
) -> Dict[str, Any]:
    return {
        "voucher_id": voucher_id,
        "unit_id": unit_id,
        "lease_start": lease_start,
    }


def move_out_payload(move_out_date: str) -> Dict[str, Any]:
    return {"move_out_date": move_out_date}


# ---------------------------------------------------------------------------
# Inspection — POST /inspections, .../complete — PRD §3.5
# ---------------------------------------------------------------------------
def create_inspection_payload(
    tenancy_id: str,
    inspection_type: str,
    scheduled_for: str,
) -> Dict[str, Any]:
    return {
        "tenancy_id": tenancy_id,
        "inspection_type": inspection_type,
        "scheduled_for": scheduled_for,
    }


def complete_inspection_payload(
    outcome: str,
    defects: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {
        "outcome": outcome,
        "defects": list(defects) if defects is not None else [],
    }


# ---------------------------------------------------------------------------
# Rent Reasonableness — POST /rent-reasonableness-records — PRD §3.6
# ---------------------------------------------------------------------------
def create_rent_reasonableness_payload(
    tenancy_id: str,
    comparable_rents_cents: List[int],
) -> Dict[str, Any]:
    return {
        "tenancy_id": tenancy_id,
        "comparable_rents_cents": list(comparable_rents_cents),
    }


# ---------------------------------------------------------------------------
# Annual Review — POST /annual-reviews/{id}/submit, ... — PRD §3.9
# ---------------------------------------------------------------------------
def submit_annual_review_payload(
    declared_gross_annual_income_cents: int,
    declared_household_size: int,
) -> Dict[str, Any]:
    return {
        "declared_gross_annual_income_cents":
            declared_gross_annual_income_cents,
        "declared_household_size": declared_household_size,
    }


def resubmit_annual_review_payload(
    declared_gross_annual_income_cents: int,
    declared_household_size: int,
) -> Dict[str, Any]:
    return {
        "declared_gross_annual_income_cents":
            declared_gross_annual_income_cents,
        "declared_household_size": declared_household_size,
    }


def mark_deficient_payload(deficiency_codes: List[str]) -> Dict[str, Any]:
    return {"deficiency_codes": list(deficiency_codes)}


# ---------------------------------------------------------------------------
# Portability — POST /portability-requests — PRD §3.10
# ---------------------------------------------------------------------------
def create_portability_request_payload(
    voucher_id: str,
    receiving_pha_id: str,
) -> Dict[str, Any]:
    return {
        "voucher_id": voucher_id,
        "receiving_pha_id": receiving_pha_id,
    }


def deny_portability_payload(denial_reason: str) -> Dict[str, Any]:
    return {"denial_reason": denial_reason}


# ---------------------------------------------------------------------------
# Clock + sweeps — PRD §2.7, §3.11, §3.12
# ---------------------------------------------------------------------------
def clock_advance_payload(to_timestamp: str) -> Dict[str, Any]:
    return {"to_timestamp": to_timestamp}


def monthly_hap_payload(pay_period_month: str) -> Dict[str, Any]:
    return {"pay_period_month": pay_period_month}


def yyyymm(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


__all__ = [
    # time
    "utcnow", "iso_utc", "iso_now", "iso_instant_utc", "parse_iso",
    "add_days", "add_seconds", "add_hours", "yyyymm",
    # random
    "random_suffix", "random_address", "random_name",
    # version
    "version_payload",
    # entities
    "create_applicant_payload",
    "create_voucher_payload",
    "create_unit_payload",
    "create_payment_standard_payload",
    "create_tenancy_payload", "move_out_payload",
    "create_inspection_payload", "complete_inspection_payload",
    "create_rent_reasonableness_payload",
    "submit_annual_review_payload", "resubmit_annual_review_payload",
    "mark_deficient_payload",
    "create_portability_request_payload", "deny_portability_payload",
    # clock + sweeps
    "clock_advance_payload", "monthly_hap_payload",
]
