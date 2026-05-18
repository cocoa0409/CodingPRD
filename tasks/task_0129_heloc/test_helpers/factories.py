"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body (PRD §3 narrative + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed/system fields are intentionally omitted
so the implementation cannot accidentally accept them as inputs.

PRD §2.6: Money values are integer cents; rates are integer basis
points.
"""
from __future__ import annotations

import random
import string
from typing import Any, Dict, Optional

from .constants import TEST_DEFAULTS


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
    return f"test.{random_suffix(8)}@example.com"


def random_address() -> str:
    return f"{random.randint(1, 9999)} Test St, Test City, CA 90210"


def random_holder_name() -> str:
    return f"Test Bank {random_suffix(4)}"


# ===========================================================================
# Borrower — PRD §3.1
# ===========================================================================
def create_borrower_payload(
    *,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.1 inputs: full_name (1..200), email (unique RFC-5322)."""
    return {
        "full_name": full_name or random_full_name(),
        "email": email or random_email(),
    }


# ===========================================================================
# Property — PRD §3.1
# ===========================================================================
def create_property_payload(
    *,
    borrower_id: str,
    address: Optional[str] = None,
    appraised_value_cents: int = TEST_DEFAULTS["APPRAISED_VALUE_CENTS"],
    occupancy: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.1 inputs: borrower_id, address (1..300),
    appraised_value_cents (>=100000), optional occupancy
    (PRIMARY/SECONDARY/INVESTMENT, defaults to PRIMARY when omitted).

    `occupancy` is intentionally OMITTED when None so tests can verify
    the PRD-declared default behavior.
    """
    payload: Dict[str, Any] = {
        "borrower_id": borrower_id,
        "address": address or random_address(),
        "appraised_value_cents": appraised_value_cents,
    }
    if occupancy is not None:
        payload["occupancy"] = occupancy
    return payload


# ===========================================================================
# SeniorLien — PRD §3.1
# ===========================================================================
def create_senior_lien_payload(
    *,
    property_id: str,
    holder_name: Optional[str] = None,
    principal_balance_cents: int = TEST_DEFAULTS[
        "SENIOR_LIEN_PRINCIPAL_CENTS"
    ],
) -> Dict[str, Any]:
    """PRD §3.1 inputs: property_id, holder_name (1..200),
    principal_balance_cents (>=0)."""
    return {
        "property_id": property_id,
        "holder_name": holder_name or random_holder_name(),
        "principal_balance_cents": principal_balance_cents,
    }


# ===========================================================================
# Heloc — PRD §3.2
# ===========================================================================
def create_heloc_payload(
    *,
    borrower_id: str,
    property_id: str,
    credit_limit_cents: int = TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    margin_bps: int = TEST_DEFAULTS["MARGIN_BPS"],
    periodic_cap_bps: int = TEST_DEFAULTS["PERIODIC_CAP_BPS"],
    lifetime_cap_bps: int = TEST_DEFAULTS["LIFETIME_CAP_BPS"],
    lifetime_floor_bps: int = TEST_DEFAULTS["LIFETIME_FLOOR_BPS"],
    repayment_term_years: int = TEST_DEFAULTS["REPAYMENT_TERM_YEARS"],
    annual_fee_cents: int = TEST_DEFAULTS["ANNUAL_FEE_CENTS"],
    annual_fee_waived_first_year: Optional[bool] = None,
    early_closure_fee_cents: int = TEST_DEFAULTS[
        "EARLY_CLOSURE_FEE_CENTS"
    ],
) -> Dict[str, Any]:
    """PRD §3.2 inputs: borrower_id, property_id, credit_limit_cents,
    margin_bps, periodic_cap_bps, lifetime_cap_bps, lifetime_floor_bps,
    repayment_term_years, annual_fee_cents,
    optional annual_fee_waived_first_year (defaults false),
    early_closure_fee_cents.

    annual_fee_waived_first_year is intentionally OMITTED when None so
    tests can verify the PRD-declared default behavior.
    """
    payload: Dict[str, Any] = {
        "borrower_id": borrower_id,
        "property_id": property_id,
        "credit_limit_cents": credit_limit_cents,
        "margin_bps": margin_bps,
        "periodic_cap_bps": periodic_cap_bps,
        "lifetime_cap_bps": lifetime_cap_bps,
        "lifetime_floor_bps": lifetime_floor_bps,
        "repayment_term_years": repayment_term_years,
        "annual_fee_cents": annual_fee_cents,
        "early_closure_fee_cents": early_closure_fee_cents,
    }
    if annual_fee_waived_first_year is not None:
        payload["annual_fee_waived_first_year"] = (
            annual_fee_waived_first_year
        )
    return payload


def activate_heloc_payload(
    *,
    prime_rate_bps: int = TEST_DEFAULTS[
        "PRIME_RATE_BPS_AT_ORIGINATION"
    ],
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD §3.2 activation inputs: prime_rate_bps and optional version
    for OCC."""
    payload: Dict[str, Any] = {"prime_rate_bps": prime_rate_bps}
    if version is not None:
        payload["version"] = version
    return payload


def close_heloc_payload(
    *,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD §3.9 close inputs: optional version for OCC."""
    payload: Dict[str, Any] = {}
    if version is not None:
        payload["version"] = version
    return payload


# ===========================================================================
# Draws — PRD §3.3
# ===========================================================================
def create_draw_payload(
    *,
    amount_cents: int,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD §3.3 inputs: amount_cents (>=10000) and optional version."""
    payload: Dict[str, Any] = {"amount_cents": amount_cents}
    if version is not None:
        payload["version"] = version
    return payload


# ===========================================================================
# Payments — PRD §3.4
# ===========================================================================
def create_payment_payload(
    *,
    amount_cents: int,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD §3.4 inputs: amount_cents (>=minimum_payment_due_cents) and
    optional version."""
    payload: Dict[str, Any] = {"amount_cents": amount_cents}
    if version is not None:
        payload["version"] = version
    return payload


# ===========================================================================
# Rate resets — PRD §3.5
# ===========================================================================
def create_rate_reset_payload(
    *,
    prime_rate_bps: int,
    version: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD §3.5 inputs: prime_rate_bps (0..3000) and optional version."""
    payload: Dict[str, Any] = {"prime_rate_bps": prime_rate_bps}
    if version is not None:
        payload["version"] = version
    return payload


# ===========================================================================
# Insurance / SeniorLienDefault — PRD §3.6
# ===========================================================================
def create_insurance_event_payload(*, event_type: str) -> Dict[str, Any]:
    """PRD §3.6 inputs: event_type in {LAPSE, REINSTATE}."""
    return {"event_type": event_type}


# ===========================================================================
# Clock advance — PRD §2.11
# ===========================================================================
def clock_advance_payload(*, seconds: int) -> Dict[str, Any]:
    """PRD §2.11: 'advances this logical clock by a supplied number of
    seconds and returns the new current_time'."""
    return {"seconds": seconds}


# ===========================================================================
# OCC version body — used to opt into PRD §2.5 concurrency check
# ===========================================================================
def version_body(version: int) -> Dict[str, Any]:
    return {"version": version}


__all__ = [
    "random_suffix",
    "random_full_name",
    "random_email",
    "random_address",
    "random_holder_name",
    "create_borrower_payload",
    "create_property_payload",
    "create_senior_lien_payload",
    "create_heloc_payload",
    "activate_heloc_payload",
    "close_heloc_payload",
    "create_draw_payload",
    "create_payment_payload",
    "create_rate_reset_payload",
    "create_insurance_event_payload",
    "clock_advance_payload",
    "version_body",
]
