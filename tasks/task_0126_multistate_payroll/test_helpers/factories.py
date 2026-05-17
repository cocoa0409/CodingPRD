"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body. Tests pass overrides for the values they want to
control. Only PRD-declared input fields are produced; computed/system
fields are intentionally omitted so the implementation cannot
accidentally accept them as inputs.

PRD §2.10 — monetary fields are integer counts of cents.
PRD §3.1 — dates are ISO 8601 YYYY-MM-DD.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Random id / string helpers
# ---------------------------------------------------------------------------
def random_suffix(n: int = 8) -> str:
    return "".join(
        random.choices(string.ascii_lowercase + string.digits, k=n),
    )


def random_full_name() -> str:
    return f"Employee {random_suffix(6)}"


# ---------------------------------------------------------------------------
# Date / time helpers — PRD §3.1 (date-only) and PRD §2.4 (timestamps)
# ---------------------------------------------------------------------------
def iso_date_str(d: date) -> str:
    """PRD §3.1: ISO 8601 calendar date in YYYY-MM-DD form."""
    return d.isoformat()


def iso_datetime_str(dt: datetime) -> str:
    """PRD §2.4: ISO 8601 UTC timestamp with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def iso_now_utc() -> str:
    """PRD §2.4: ISO 8601 UTC timestamp with three fractional digits."""
    return iso_datetime_str(datetime.now(tz=timezone.utc))


def add_days(d: date, days: int) -> date:
    return d + timedelta(days=days)


# ===========================================================================
# Clock — PRD §3.9
# ===========================================================================
def clock_advance_payload(*, to_iso: str) -> Dict[str, Any]:
    """PRD §3.9: '/_clock/advance ... advances the server's logical
    clock to a supplied to_iso instant'."""
    return {"to_iso": to_iso}


# ===========================================================================
# Employee — PRD §3.1
# ===========================================================================
def create_employee_payload(
    *,
    full_name: Optional[str] = None,
    hire_date: Optional[str] = None,
    work_state: str = "TX",
    work_locality: Optional[str] = None,
    hourly_rate_cents: int = 12_500,
) -> Dict[str, Any]:
    """PRD §3.1 inputs: full_name, hire_date, work_state, optional
    work_locality (defaults to NONE on server), hourly_rate_cents."""
    payload: Dict[str, Any] = {
        "full_name": full_name or random_full_name(),
        "hire_date": hire_date or iso_date_str(date(2024, 1, 1)),
        "work_state": work_state,
        "hourly_rate_cents": hourly_rate_cents,
    }
    if work_locality is not None:
        payload["work_locality"] = work_locality
    return payload


def terminate_employee_payload(*, version: Optional[int] = None
                                ) -> Dict[str, Any]:
    """PRD §3.1: terminate accepts only an optional version for OCC."""
    return {"version": version} if version is not None else {}


# ===========================================================================
# W-4 Profile — PRD §3.1
# ===========================================================================
def create_w4_profile_payload(
    *,
    effective_pay_period_id: str,
    filing_status: str = "SINGLE",
    dependents_amount_cents: Optional[int] = None,
    other_income_cents: Optional[int] = None,
    additional_withholding_cents: Optional[int] = None,
    state_allowances: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD §3.1 W-4 profile creation: filing_status,
    optional dependents/other_income/additional_withholding/
    state_allowances (default 0), and effective_pay_period_id."""
    payload: Dict[str, Any] = {
        "filing_status": filing_status,
        "effective_pay_period_id": effective_pay_period_id,
    }
    if dependents_amount_cents is not None:
        payload["dependents_amount_cents"] = dependents_amount_cents
    if other_income_cents is not None:
        payload["other_income_cents"] = other_income_cents
    if additional_withholding_cents is not None:
        payload["additional_withholding_cents"] = (
            additional_withholding_cents
        )
    if state_allowances is not None:
        payload["state_allowances"] = state_allowances
    return payload


def prefill_w4_payload(*, effective_pay_period_id: str) -> Dict[str, Any]:
    """PRD §3.1: 'the specialist supplies only the new
    effective_pay_period_id' for the prefill endpoint."""
    return {"effective_pay_period_id": effective_pay_period_id}


# ===========================================================================
# Garnishment Order — PRD §3.5
# ===========================================================================
def create_garnishment_order_payload(
    *,
    employee_id: str,
    order_type: str = "CREDITOR",
    total_owed_cents: int = 500_000,
    cap_pct_of_disposable: int = 15,
    effective_pay_date: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.5 garnishment inputs: employee_id, order_type,
    total_owed_cents, cap_pct_of_disposable, effective_pay_date."""
    return {
        "employee_id": employee_id,
        "order_type": order_type,
        "total_owed_cents": total_owed_cents,
        "cap_pct_of_disposable": cap_pct_of_disposable,
        "effective_pay_date": (
            effective_pay_date or iso_date_str(date(2024, 1, 1))
        ),
    }


# ===========================================================================
# Pay Period — PRD §3.2
# ===========================================================================
def create_pay_period_payload(
    *,
    period_start: Optional[str] = None,
    period_end: Optional[str] = None,
    pay_date: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.2 pay period inputs: period_start, period_end, pay_date."""
    # Default: a biweekly cycle 2024-06-03..2024-06-16 paid 2024-06-21.
    return {
        "period_start": period_start or iso_date_str(date(2024, 6, 3)),
        "period_end": period_end or iso_date_str(date(2024, 6, 16)),
        "pay_date": pay_date or iso_date_str(date(2024, 6, 21)),
    }


def biweekly_pay_period_payload(
    start: date,
    *,
    pay_offset_days: int = 5,
) -> Dict[str, Any]:
    """Build a biweekly (14-day) pay period starting at `start`, with
    pay_date set to `period_end + pay_offset_days`."""
    end = start + timedelta(days=13)
    pay = end + timedelta(days=pay_offset_days)
    return {
        "period_start": iso_date_str(start),
        "period_end": iso_date_str(end),
        "pay_date": iso_date_str(pay),
    }


# ===========================================================================
# Payroll Item — PRD §3.3
# ===========================================================================
def create_payroll_item_payload(
    *,
    employee_id: str,
    regular_hours: Optional[float] = None,
    overtime_hours: Optional[float] = None,
    double_hours: Optional[float] = None,
    retro_adjustment_cents: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD §3.3 payroll-item inputs: employee_id plus four optional
    hour/retro fields (defaulting to 0 when omitted)."""
    payload: Dict[str, Any] = {"employee_id": employee_id}
    if regular_hours is not None:
        payload["regular_hours"] = regular_hours
    if overtime_hours is not None:
        payload["overtime_hours"] = overtime_hours
    if double_hours is not None:
        payload["double_hours"] = double_hours
    if retro_adjustment_cents is not None:
        payload["retro_adjustment_cents"] = retro_adjustment_cents
    return payload


def update_payroll_item_payload(
    *,
    regular_hours: Optional[float] = None,
    overtime_hours: Optional[float] = None,
    double_hours: Optional[float] = None,
    retro_adjustment_cents: Optional[int] = None,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD §3.3 update inputs: any subset of hours/retro, plus
    optional OCC version."""
    payload: Dict[str, Any] = {}
    if regular_hours is not None:
        payload["regular_hours"] = regular_hours
    if overtime_hours is not None:
        payload["overtime_hours"] = overtime_hours
    if double_hours is not None:
        payload["double_hours"] = double_hours
    if retro_adjustment_cents is not None:
        payload["retro_adjustment_cents"] = retro_adjustment_cents
    if version is not None:
        payload["version"] = version
    return payload


# ===========================================================================
# Paycheck — PRD §3.7
# ===========================================================================
def issue_correction_payload(*, target_pay_period_id: str,
                              version: Optional[int] = None
                              ) -> Dict[str, Any]:
    """PRD §3.7: 'A PayrollSpecialist calls the issue-correction
    capability supplying a target_pay_period_id for the new draft
    paycheck.'"""
    payload: Dict[str, Any] = {
        "target_pay_period_id": target_pay_period_id,
    }
    if version is not None:
        payload["version"] = version
    return payload


# ===========================================================================
# Remittance Period — PRD §3.10
# ===========================================================================
def create_remittance_payload(*, tax_year: int, tax_month: int
                                ) -> Dict[str, Any]:
    """PRD §3.10: 'created ... with tax_year and tax_month (1 through
    12)'."""
    return {"tax_year": tax_year, "tax_month": tax_month}


# ===========================================================================
# Tax Bracket Table — PRD §3.9
# ===========================================================================
def create_tax_bracket_table_payload(
    *,
    jurisdiction: str,
    filing_status: str,
    tax_year: int,
    brackets: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """PRD §3.9 tax-bracket-table inputs: jurisdiction, filing_status,
    tax_year, brackets (ordered array of bracket records)."""
    return {
        "jurisdiction": jurisdiction,
        "filing_status": filing_status,
        "tax_year": tax_year,
        "brackets": brackets,
    }


# ===========================================================================
# Optional-version helper — PRD §2.5
# ===========================================================================
def version_body(version: Optional[int]) -> Dict[str, Any]:
    """Build an OCC body fragment carrying version only when supplied.

    PRD §2.5: 'When version is omitted from the body, no OCC check is
    performed and the mutation proceeds.'
    """
    return {"version": version} if version is not None else {}


__all__ = [
    "random_suffix",
    "random_full_name",
    "iso_date_str",
    "iso_datetime_str",
    "iso_now_utc",
    "add_days",
    "clock_advance_payload",
    "create_employee_payload",
    "terminate_employee_payload",
    "create_w4_profile_payload",
    "prefill_w4_payload",
    "create_garnishment_order_payload",
    "create_pay_period_payload",
    "biweekly_pay_period_payload",
    "create_payroll_item_payload",
    "update_payroll_item_payload",
    "issue_correction_payload",
    "create_remittance_payload",
    "create_tax_bracket_table_payload",
    "version_body",
]
