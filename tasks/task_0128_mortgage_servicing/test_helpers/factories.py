"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body (PRD §3 narrative + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed/system fields are intentionally omitted
so the implementation cannot accidentally accept them as inputs.

PRD §2.4: Money values are integer cents. Dates are ISO 8601 timestamps
at UTC midnight (or YYYY-MM-DD).
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Random id / string helpers
# ---------------------------------------------------------------------------
def random_suffix(n: int = 8) -> str:
    return "".join(
        random.choices(string.ascii_lowercase + string.digits, k=n),
    )


def random_full_name() -> str:
    return f"Test Borrower {random_suffix(6)}"


def random_email() -> str:
    return f"test.{random_suffix(6)}@example.com"


# ---------------------------------------------------------------------------
# Date / time helpers — PRD §2.4
# ---------------------------------------------------------------------------
def iso_date_str(d: date) -> str:
    """ISO 8601 calendar date in YYYY-MM-DD form."""
    return d.isoformat()


def iso_datetime_utc_midnight(d: date) -> str:
    """PRD §2.4: 'Date-only quantities ... are stored as ISO 8601
    timestamps at UTC midnight.'"""
    return d.isoformat() + "T00:00:00.000Z"


def iso_now_utc() -> str:
    """PRD §2.4 ISO 8601 UTC timestamp with three fractional digits."""
    dt = datetime.now(tz=timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def today_utc() -> date:
    return datetime.now(tz=timezone.utc).date()


def date_plus_days(d: date, days: int) -> date:
    return d + timedelta(days=days)


# ===========================================================================
# Borrower — PRD §3.1
# ===========================================================================
def create_borrower_payload(
    *,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.1 inputs: full_name (non-empty, max 200 chars), email."""
    return {
        "full_name": full_name or random_full_name(),
        "email": email or random_email(),
    }


# ===========================================================================
# Loan — PRD §3.1
# ===========================================================================
def create_loan_payload(
    *,
    borrower_id: str,
    origination_date: Optional[str] = None,
    original_principal_cents: int = 20_000_000,
    original_appraised_value_cents: int = 25_000_000,
    interest_rate_bps: int = 625,
    term_months: int = 360,
    pmi_monthly_cents: Optional[int] = None,
    monthly_escrow_payment_cents: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD §3.1 inputs: borrower_id, origination_date,
    original_principal_cents (>= 100,000), original_appraised_value_cents
    (>0), interest_rate_bps (1..5000), term_months (60..480), optional
    pmi_monthly_cents and monthly_escrow_payment_cents."""
    if origination_date is None:
        # Choose a stable past date to keep clock arithmetic predictable.
        origination_date = iso_datetime_utc_midnight(today_utc())
    payload: Dict[str, Any] = {
        "borrower_id": borrower_id,
        "origination_date": origination_date,
        "original_principal_cents": original_principal_cents,
        "original_appraised_value_cents": original_appraised_value_cents,
        "interest_rate_bps": interest_rate_bps,
        "term_months": term_months,
    }
    if pmi_monthly_cents is not None:
        payload["pmi_monthly_cents"] = pmi_monthly_cents
    if monthly_escrow_payment_cents is not None:
        payload["monthly_escrow_payment_cents"] = (
            monthly_escrow_payment_cents
        )
    return payload


# ===========================================================================
# Payment — PRD §3.2
# ===========================================================================
def create_payment_payload(
    *,
    received_date: str,
    amount_cents: int,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD §3.2 inputs: received_date, amount_cents (>0), optional
    version for OCC."""
    payload: Dict[str, Any] = {
        "received_date": received_date,
        "amount_cents": amount_cents,
    }
    if version is not None:
        payload["version"] = version
    return payload


# ===========================================================================
# Escrow analysis — PRD §3.3
# ===========================================================================
def create_escrow_analysis_payload(
    *,
    analysis_date: str,
    starting_balance_cents: int,
) -> Dict[str, Any]:
    """PRD §3.3 inputs: analysis_date, starting_balance_cents."""
    return {
        "analysis_date": analysis_date,
        "starting_balance_cents": starting_balance_cents,
    }


# ===========================================================================
# Disbursement — PRD §3.3
# ===========================================================================
def create_disbursement_payload(
    *,
    type: str,
    scheduled_date: str,
    amount_cents: int,
) -> Dict[str, Any]:
    """PRD §3.3 inputs: type (PROPERTY_TAX, HAZARD_INSURANCE,
    SURPLUS_REFUND), scheduled_date, amount_cents (>0)."""
    return {
        "type": type,
        "scheduled_date": scheduled_date,
        "amount_cents": amount_cents,
    }


# ===========================================================================
# Forbearance plan — PRD §3.4
# ===========================================================================
def create_forbearance_plan_payload(
    *,
    start_date: str,
    months: int,
    repayment_method: str,
) -> Dict[str, Any]:
    """PRD §3.4 inputs: start_date, months (1..12), repayment_method
    (LUMP_SUM, REPAYMENT_PLAN_12M, DEFERRAL)."""
    return {
        "start_date": start_date,
        "months": months,
        "repayment_method": repayment_method,
    }


# ===========================================================================
# PMI removal request — PRD §3.5
# ===========================================================================
def create_pmi_removal_request_payload(
    *,
    trigger: str,
    current_appraised_value_cents: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD §3.5 inputs: trigger (BORROWER_REQUEST, AUTO_TERMINATION),
    optional current_appraised_value_cents (required for
    BORROWER_REQUEST; ignored for AUTO_TERMINATION)."""
    payload: Dict[str, Any] = {"trigger": trigger}
    if current_appraised_value_cents is not None:
        payload["current_appraised_value_cents"] = (
            current_appraised_value_cents
        )
    return payload


def deny_pmi_removal_payload(*, denial_reason: str) -> Dict[str, Any]:
    """PRD §3.5: the deny endpoint body carries denial_reason
    (LTV_TOO_HIGH, PAYMENT_HISTORY_INSUFFICIENT, LOAN_NOT_CURRENT)."""
    return {"denial_reason": denial_reason}


# ===========================================================================
# Foreclosure case — PRD §3.6
# ===========================================================================
def create_foreclosure_case_payload(
    *,
    loan_id: str,
    foreclosure_costs_cents: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD §3.6 inputs: loan_id, optional foreclosure_costs_cents
    (defaults to zero)."""
    payload: Dict[str, Any] = {"loan_id": loan_id}
    if foreclosure_costs_cents is not None:
        payload["foreclosure_costs_cents"] = foreclosure_costs_cents
    return payload


def schedule_auction_payload(*, auction_date: str) -> Dict[str, Any]:
    """PRD §3.6: schedule-auction body carries auction_date."""
    return {"auction_date": auction_date}


def reinstate_foreclosure_payload(
    *, payment_amount_cents: int,
) -> Dict[str, Any]:
    """PRD §3.6: reinstate body carries payment_amount_cents."""
    return {"payment_amount_cents": payment_amount_cents}


# ===========================================================================
# Mediation case — PRD §3.7
# ===========================================================================
def extend_mediation_offer_payload(
    *,
    offered_new_rate_bps: Optional[int] = None,
    offered_term_extension_months: Optional[int] = None,
    offered_principal_forbearance_cents: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD §3.7 inputs for /extend-offer: any of offered_new_rate_bps,
    offered_term_extension_months, offered_principal_forbearance_cents."""
    payload: Dict[str, Any] = {}
    if offered_new_rate_bps is not None:
        payload["offered_new_rate_bps"] = offered_new_rate_bps
    if offered_term_extension_months is not None:
        payload["offered_term_extension_months"] = (
            offered_term_extension_months
        )
    if offered_principal_forbearance_cents is not None:
        payload["offered_principal_forbearance_cents"] = (
            offered_principal_forbearance_cents
        )
    return payload


def reject_mediation_offer_payload(*, rejection_reason: str
                                   ) -> Dict[str, Any]:
    """PRD §3.7: reject-offer body carries rejection_reason
    (DTI_TOO_HIGH, AFFORDABILITY_FLOOR, BORROWER_REFUSED)."""
    return {"rejection_reason": rejection_reason}


# ===========================================================================
# Clock control — PRD §2.9, §3.8
# ===========================================================================
def clock_advance_payload(*, days: int) -> Dict[str, Any]:
    """PRD §3.8: /_clock/advance body carries `days`."""
    return {"days": days}


# ===========================================================================
# Optional-version helper — PRD §2.5
# ===========================================================================
def version_body(version: Optional[int]) -> Dict[str, Any]:
    """Build an OCC body fragment carrying `version` only when supplied.

    PRD §2.5: "When the caller omits version, the optimistic check is
    skipped and the request applies last-writer-wins."
    """
    return {"version": version} if version is not None else {}


__all__ = [
    "random_suffix",
    "random_full_name",
    "random_email",
    "iso_date_str",
    "iso_datetime_utc_midnight",
    "iso_now_utc",
    "today_utc",
    "date_plus_days",
    "create_borrower_payload",
    "create_loan_payload",
    "create_payment_payload",
    "create_escrow_analysis_payload",
    "create_disbursement_payload",
    "create_forbearance_plan_payload",
    "create_pmi_removal_request_payload",
    "deny_pmi_removal_payload",
    "create_foreclosure_case_payload",
    "schedule_auction_payload",
    "reinstate_foreclosure_payload",
    "extend_mediation_offer_payload",
    "reject_mediation_offer_payload",
    "clock_advance_payload",
    "version_body",
]
