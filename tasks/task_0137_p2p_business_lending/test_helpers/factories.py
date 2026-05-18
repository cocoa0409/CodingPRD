"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body (PRD §3 narrative + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed/system fields are intentionally omitted
so the implementation cannot accidentally accept them as inputs.

PRD §2.8: Money values are integer cents.
"""
from __future__ import annotations

import random
import string
from typing import Any, Dict, Optional

from .constants import (
    DEFAULT_LATE_FEE_CENTS,
    DEFAULT_MAX_BORROWER_CONCENTRATION_BPS,
    DEFAULT_ORIGINATION_FEE_BPS,
    DEFAULT_SERVICING_FEE_BPS,
    TEST_DEFAULTS,
)


# ---------------------------------------------------------------------------
# Random id / string helpers
# ---------------------------------------------------------------------------
def random_suffix(n: int = 8) -> str:
    return "".join(
        random.choices(string.ascii_lowercase + string.digits, k=n),
    )


def random_legal_name() -> str:
    return f"Test Borrower LLC {random_suffix(6)}"


def random_ein() -> str:
    """Two-digit prefix, dash, seven-digit suffix — IRS-style EIN
    string. Random suffix guarantees uniqueness across tests on the
    same platform (PRD §3.2 EIN uniqueness)."""
    return f"{random.randint(10, 99)}-{random.randint(1000000, 9999999)}"


def random_investor_name() -> str:
    return f"Test Investor {random_suffix(6)}"


def random_officer_name() -> str:
    return f"Test Officer {random_suffix(6)}"


def random_platform_name() -> str:
    return f"Test Platform {random_suffix(6)}"


# ===========================================================================
# Platform — PRD §3.1
# ===========================================================================
def create_platform_payload(
    *,
    name: Optional[str] = None,
    currency: Optional[str] = None,
    origination_fee_bps: Optional[int] = None,
    servicing_fee_bps: Optional[int] = None,
    late_fee_cents: Optional[int] = None,
    max_borrower_concentration_bps: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD §3.1 inputs: name (required), optional currency,
    origination_fee_bps, servicing_fee_bps, late_fee_cents,
    max_borrower_concentration_bps. All optional values fall back to
    PRD-declared defaults at the server."""
    payload: Dict[str, Any] = {
        "name": name or random_platform_name(),
    }
    if currency is not None:
        payload["currency"] = currency
    if origination_fee_bps is not None:
        payload["origination_fee_bps"] = origination_fee_bps
    if servicing_fee_bps is not None:
        payload["servicing_fee_bps"] = servicing_fee_bps
    if late_fee_cents is not None:
        payload["late_fee_cents"] = late_fee_cents
    if max_borrower_concentration_bps is not None:
        payload["max_borrower_concentration_bps"] = (
            max_borrower_concentration_bps
        )
    return payload


def advance_clock_payload(*, days: int) -> Dict[str, Any]:
    """PRD §3.1: 'the body parameter is named days and represents the
    count of logical days to advance.'"""
    return {"days": days}


# ===========================================================================
# Borrower — PRD §3.2
# ===========================================================================
def create_borrower_payload(
    *,
    legal_name: Optional[str] = None,
    ein: Optional[str] = None,
    annual_revenue_cents: int = TEST_DEFAULTS[
        "BORROWER_ANNUAL_REVENUE_CENTS"
    ],
    requested_amount_cents: int = TEST_DEFAULTS[
        "BORROWER_REQUESTED_AMOUNT_CENTS"
    ],
) -> Dict[str, Any]:
    """PRD §3.2 inputs: legal_name, federal ein, self-reported
    annual_revenue_cents, requested_amount_cents."""
    return {
        "legal_name": legal_name or random_legal_name(),
        "ein": ein or random_ein(),
        "annual_revenue_cents": annual_revenue_cents,
        "requested_amount_cents": requested_amount_cents,
    }


# ===========================================================================
# PlaidSnapshot — PRD §3.2
# ===========================================================================
def create_plaid_snapshot_payload(
    *,
    deposits_last_90d_cents: int = TEST_DEFAULTS[
        "PLAID_DEPOSITS_LAST_90D_CENTS"
    ],
    avg_daily_balance_cents: int = TEST_DEFAULTS[
        "PLAID_AVG_DAILY_BALANCE_CENTS"
    ],
    nsf_count_last_90d: int = TEST_DEFAULTS["PLAID_NSF_COUNT"],
    existing_debt_service_cents: int = TEST_DEFAULTS[
        "PLAID_DEBT_SERVICE_CENTS"
    ],
) -> Dict[str, Any]:
    """PRD §3.2 inputs: deposits_last_90d_cents, avg_daily_balance_cents,
    nsf_count_last_90d, existing_debt_service_cents."""
    return {
        "deposits_last_90d_cents": deposits_last_90d_cents,
        "avg_daily_balance_cents": avg_daily_balance_cents,
        "nsf_count_last_90d": nsf_count_last_90d,
        "existing_debt_service_cents": existing_debt_service_cents,
    }


# ===========================================================================
# Investor — PRD §3.8
# ===========================================================================
def create_investor_payload(
    *,
    display_name: Optional[str] = None,
    accreditation_status: str = "ACCREDITED",
    committed_capital_cents: int = TEST_DEFAULTS[
        "INVESTOR_COMMITTED_CAPITAL_CENTS"
    ],
) -> Dict[str, Any]:
    """PRD §3.8 inputs: display_name, accreditation_status
    (ACCREDITED | NON_ACCREDITED), committed_capital_cents."""
    return {
        "display_name": display_name or random_investor_name(),
        "accreditation_status": accreditation_status,
        "committed_capital_cents": committed_capital_cents,
    }


def deposit_payload(*, amount_cents: int) -> Dict[str, Any]:
    """PRD §3.8: deposit body carries amount_cents."""
    return {"amount_cents": amount_cents}


# ===========================================================================
# LoanListing — PRD §3.3
# ===========================================================================
def create_listing_payload(
    *,
    principal_cents: int = TEST_DEFAULTS["PRINCIPAL_CENTS"],
    term_months: int = TEST_DEFAULTS["TERM_MONTHS"],
) -> Dict[str, Any]:
    """PRD §3.3 inputs: principal_cents, term_months (12 | 24 | 36 |
    48 | 60)."""
    return {
        "principal_cents": principal_cents,
        "term_months": term_months,
    }


# ===========================================================================
# Investment — PRD §3.3
# ===========================================================================
def create_investment_payload(
    *,
    amount_cents: int,
) -> Dict[str, Any]:
    """PRD §3.3 inputs: amount_cents (>= 2500, multiple of 100)."""
    return {"amount_cents": amount_cents}


# ===========================================================================
# Payment — PRD §3.5
# ===========================================================================
def create_payment_payload(
    *,
    amount_cents: int,
) -> Dict[str, Any]:
    """PRD §3.5 inputs: amount_cents (positive integer cents)."""
    return {"amount_cents": amount_cents}


# ===========================================================================
# ComplianceOfficer — PRD §3.9
# ===========================================================================
def create_compliance_officer_payload(
    *,
    display_name: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.9 inputs: display_name (required)."""
    return {"display_name": display_name or random_officer_name()}


__all__ = [
    "random_suffix",
    "random_legal_name",
    "random_ein",
    "random_investor_name",
    "random_officer_name",
    "random_platform_name",
    "create_platform_payload",
    "advance_clock_payload",
    "create_borrower_payload",
    "create_plaid_snapshot_payload",
    "create_investor_payload",
    "deposit_payload",
    "create_listing_payload",
    "create_investment_payload",
    "create_payment_payload",
    "create_compliance_officer_payload",
]
