"""Payload factories — one per input-bearing endpoint.

Every factory emits the exact field names PRD §3 specifies. Optional
fields are omitted by default unless the caller passes them; explicit
None values are also passed through so a test can assert how the
implementation treats nulls.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------
def iso_date(year: int, month: int, day: int) -> str:
    return date(year, month, day).isoformat()


def date_plus(base: str, days: int) -> str:
    """Add `days` to YYYY-MM-DD string and return YYYY-MM-DD."""
    d = date.fromisoformat(base) + timedelta(days=days)
    return d.isoformat()


# ---------------------------------------------------------------------------
# Plan — PRD §3.1 / §2.11
# ---------------------------------------------------------------------------
def create_plan_payload(
    *,
    plan_name: Optional[str] = None,
    plan_year: Optional[int] = None,
    match_formula_type: str = "SAFE_HARBOR_BASIC",
    tiered_brackets: Optional[List[Dict[str, Any]]] = None,
    vesting_schedule_type: str = "CLIFF",
    cliff_years: Optional[int] = 3,
    graded_percentages: Optional[List[int]] = None,
    rmd_age: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /plans — PRD §3.1.

    Defaults: SAFE_HARBOR_BASIC + CLIFF(3) so the simplest valid
    configuration round-trips. The two axes are independently
    overridable: pass match_formula_type="TIERED" together with
    tiered_brackets=[...] for the tiered variant; pass
    vesting_schedule_type="GRADED" together with graded_percentages=[...]
    for the graded variant.
    """
    payload: Dict[str, Any] = {
        "plan_name": plan_name or TEST_DEFAULTS["PLAN_NAME"],
        "plan_year": plan_year or TEST_DEFAULTS["PLAN_YEAR"],
        "match_formula_type": match_formula_type,
        "vesting_schedule_type": vesting_schedule_type,
    }

    # Variant-specific config — PRD §2.11.
    if match_formula_type == "TIERED":
        payload["tiered_brackets"] = (
            tiered_brackets if tiered_brackets is not None
            else TEST_DEFAULTS["TIERED_BRACKETS_BASIC"]
        )
    elif tiered_brackets is not None:
        # caller wants to send tiered_brackets even under SAFE_HARBOR_BASIC
        payload["tiered_brackets"] = tiered_brackets

    if vesting_schedule_type == "CLIFF":
        if cliff_years is not None:
            payload["cliff_years"] = cliff_years
    elif vesting_schedule_type == "GRADED":
        payload["graded_percentages"] = (
            graded_percentages if graded_percentages is not None
            else TEST_DEFAULTS["GRADED_PERCENTAGES"]
        )
    else:
        # Caller passed an unknown variant — pass values through verbatim
        # so a test exercising ERR_INVALID_PLAN_CONFIG can observe rejection.
        if cliff_years is not None:
            payload["cliff_years"] = cliff_years
        if graded_percentages is not None:
            payload["graded_percentages"] = graded_percentages

    if rmd_age is not None:
        payload["rmd_age"] = rmd_age

    payload.update(overrides)
    return payload


def clock_advance_payload(new_date: str, **overrides: Any) -> Dict[str, Any]:
    """POST /plans/{planId}/_clock/advance — PRD §3.1 / §2.7."""
    payload: Dict[str, Any] = {"new_date": new_date}
    payload.update(overrides)
    return payload


def version_body(version: int) -> Dict[str, Any]:
    """OCC version envelope — PRD §2.10."""
    return {"version": version}


# ---------------------------------------------------------------------------
# Participant — PRD §3.2
# ---------------------------------------------------------------------------
def create_participant_payload(
    *,
    employee_external_id: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    hire_date: Optional[str] = None,
    annual_compensation_cents: Optional[int] = None,
    elected_deferral_pct: Optional[float] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /plans/{planId}/participants — PRD §3.2."""
    import uuid as _uuid
    payload: Dict[str, Any] = {
        "employee_external_id": (
            employee_external_id
            or f"emp-{_uuid.uuid4().hex[:12]}"
        ),
        "date_of_birth": (
            date_of_birth or TEST_DEFAULTS["DATE_OF_BIRTH"]
        ),
        "hire_date": hire_date or TEST_DEFAULTS["HIRE_DATE"],
        "annual_compensation_cents": (
            annual_compensation_cents
            if annual_compensation_cents is not None
            else TEST_DEFAULTS["ANNUAL_COMPENSATION_CENTS"]
        ),
        "elected_deferral_pct": (
            elected_deferral_pct
            if elected_deferral_pct is not None
            else TEST_DEFAULTS["ELECTED_DEFERRAL_PCT"]
        ),
    }
    payload.update(overrides)
    return payload


def update_deferral_payload(
    elected_deferral_pct: float,
    *,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PATCH /plans/{planId}/participants/{id}/deferral — PRD §3.2."""
    payload: Dict[str, Any] = {
        "elected_deferral_pct": elected_deferral_pct,
    }
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ContributionRecord — PRD §3.3
# ---------------------------------------------------------------------------
def create_contribution_payload(
    *,
    pay_period_end: str,
    gross_pay_cents: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /plans/{planId}/participants/{id}/contribution-records —
    PRD §3.3. The implementation computes employee_amount_cents and
    employer_match_cents server-side; only the two inputs travel in.
    """
    payload: Dict[str, Any] = {
        "pay_period_end": pay_period_end,
        "gross_pay_cents": gross_pay_cents,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Loan — PRD §3.5
# ---------------------------------------------------------------------------
def create_loan_payload(
    *,
    requested_amount_cents: int,
    term_months: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /plans/{planId}/participants/{id}/loans — PRD §3.5."""
    payload: Dict[str, Any] = {
        "requested_amount_cents": requested_amount_cents,
        "term_months": term_months,
    }
    payload.update(overrides)
    return payload


def create_loan_repayment_payload(
    *,
    payment_amount_cents: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /plans/{planId}/participants/{id}/loans/{loanId}/repayments
    — PRD §3.5.
    """
    payload: Dict[str, Any] = {
        "payment_amount_cents": payment_amount_cents,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# HardshipWithdrawal — PRD §3.6
# ---------------------------------------------------------------------------
def create_hardship_payload(
    *,
    requested_amount_cents: int,
    hardship_reason_code: str = "MEDICAL",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /plans/{planId}/participants/{id}/hardship-withdrawals —
    PRD §3.6.
    """
    payload: Dict[str, Any] = {
        "requested_amount_cents": requested_amount_cents,
        "hardship_reason_code": hardship_reason_code,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# RMDSchedule — PRD §3.7
# ---------------------------------------------------------------------------
def create_rmd_payload(
    *,
    rmd_year: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /plans/{planId}/participants/{id}/rmd-schedules — PRD §3.7."""
    payload: Dict[str, Any] = {"rmd_year": rmd_year}
    payload.update(overrides)
    return payload


def fulfill_rmd_payload(
    *,
    distributed_amount_cents: int,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST .../rmd-schedules/{id}/fulfill — PRD §3.7."""
    payload: Dict[str, Any] = {
        "distributed_amount_cents": distributed_amount_cents,
    }
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


__all__ = [
    "iso_date",
    "date_plus",
    "create_plan_payload",
    "clock_advance_payload",
    "version_body",
    "create_participant_payload",
    "update_deferral_payload",
    "create_contribution_payload",
    "create_loan_payload",
    "create_loan_repayment_payload",
    "create_hardship_payload",
    "create_rmd_payload",
    "fulfill_rmd_payload",
]
