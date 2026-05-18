"""Payload factories — one per endpoint that accepts an input body.

Each factory emits the exact JSON-body schema the PRD declares (PRD §3
narrative + §4 endpoint table). Tests pass overrides for the values they
want to control. Only PRD-declared input fields are produced; computed
/ system fields are omitted so the implementation cannot accidentally
accept them as inputs.

PRD §2.7: every monetary value crosses the wire as an integer count of
US-cent units.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Random / date helpers
# ---------------------------------------------------------------------------
def random_suffix(n: int = 8) -> str:
    return "".join(
        random.choices(string.ascii_lowercase + string.digits, k=n),
    )


def random_legal_name() -> str:
    return f"Test Customer {random_suffix(6)}"


def random_symbol() -> str:
    """1..5 uppercase A-Z per PRD §3.3."""
    n = random.randint(1, 5)
    return "".join(random.choices(string.ascii_uppercase, k=n))


def today_utc() -> date:
    return datetime.now(tz=timezone.utc).date()


def iso_date_str(d: date) -> str:
    """ISO 8601 calendar date in YYYY-MM-DD form (PRD §3.1
    date_of_birth)."""
    return d.isoformat()


def years_ago_dob(years: int) -> str:
    """date_of_birth such that the customer is exactly `years` years old
    today (UTC)."""
    today = today_utc()
    return (
        date(today.year - years, today.month, today.day).isoformat()
    )


def iso_now_utc() -> str:
    """PRD §2.4 ISO 8601 UTC timestamp with three fractional digits."""
    dt = datetime.now(tz=timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


# ===========================================================================
# Customer creation — PRD §3.1
# ===========================================================================
def create_customer_payload(
    *,
    legal_name: Optional[str] = None,
    date_of_birth: Optional[str] = None,
    ssn_last4: Optional[str] = None,
    annual_income_cents: Optional[int] = None,
    liquid_net_worth_cents: Optional[int] = None,
    total_net_worth_cents: Optional[int] = None,
    years_options_experience: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD §3.1 inputs only — legal_name, date_of_birth, ssn_last4,
    annual_income_cents, liquid_net_worth_cents, total_net_worth_cents,
    years_options_experience.
    """
    return {
        "legal_name": (
            legal_name if legal_name is not None
            else random_legal_name()
        ),
        "date_of_birth": (
            date_of_birth if date_of_birth is not None
            else TEST_DEFAULTS["DATE_OF_BIRTH"]
        ),
        "ssn_last4": (
            ssn_last4 if ssn_last4 is not None
            else TEST_DEFAULTS["SSN_LAST4"]
        ),
        "annual_income_cents": (
            annual_income_cents if annual_income_cents is not None
            else TEST_DEFAULTS["ANNUAL_INCOME_CENTS"]
        ),
        "liquid_net_worth_cents": (
            liquid_net_worth_cents
            if liquid_net_worth_cents is not None
            else TEST_DEFAULTS["LIQUID_NET_WORTH_CENTS"]
        ),
        "total_net_worth_cents": (
            total_net_worth_cents
            if total_net_worth_cents is not None
            else TEST_DEFAULTS["TOTAL_NET_WORTH_CENTS"]
        ),
        "years_options_experience": (
            years_options_experience
            if years_options_experience is not None
            else TEST_DEFAULTS["YEARS_OPTIONS_EXPERIENCE"]
        ),
    }


# ===========================================================================
# Account creation — PRD §3.1
# ===========================================================================
def create_account_payload(
    *,
    customer_id: str,
    account_type: str = "CASH",
) -> Dict[str, Any]:
    """PRD §3.1 inputs — customer_id, account_type in {CASH, MARGIN_REG_T,
    MARGIN_PMA}."""
    return {
        "customer_id": customer_id,
        "account_type": account_type,
    }


# ===========================================================================
# KYC submission — PRD §3.1
# ===========================================================================
def submit_kyc_payload(
    *,
    legal_name_for_w9: str,
    government_id_type: str = "PASSPORT",
    government_id_number: Optional[str] = None,
    address_line1: Optional[str] = None,
    address_country: str = "US",
    w9_signed_name: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.1 inputs — government_id_type, government_id_number,
    address_line1, address_country, w9_signed_name.

    `legal_name_for_w9` defaults the W-9 signed name to the customer's
    own legal_name so the W-9 match passes by default; tests that want
    mismatch override `w9_signed_name` explicitly.
    """
    return {
        "government_id_type": government_id_type,
        "government_id_number": (
            government_id_number if government_id_number is not None
            else TEST_DEFAULTS["GOVERNMENT_ID_NUMBER"]
        ),
        "address_line1": (
            address_line1 if address_line1 is not None
            else TEST_DEFAULTS["ADDRESS_LINE1"]
        ),
        "address_country": address_country,
        "w9_signed_name": (
            w9_signed_name if w9_signed_name is not None
            else legal_name_for_w9
        ),
    }


def kyc_decision_payload(*, decision: str) -> Dict[str, Any]:
    """PRD §3.1: body={decision:'VERIFY'} or body={decision:'REJECT'}."""
    return {"decision": decision}


# ===========================================================================
# Options approvals — PRD §3.2
# ===========================================================================
def create_options_approval_payload(
    *,
    account_id: str,
    requested_level: int,
) -> Dict[str, Any]:
    """PRD §3.2: requested_level between 1 and 4 inclusive."""
    return {
        "account_id": account_id,
        "requested_level": requested_level,
    }


def decide_options_approval_payload(
    *,
    decision: str,
    approved_level: Optional[int] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.2 decision body — APPROVE / REQUEST_REVISION / REJECT.

    APPROVE requires approved_level; REQUEST_REVISION and REJECT require
    notes (PRD §3.2: 'Requesting a revision requires non-empty notes
    ...'; 'Rejection from UNDER_REVIEW likewise requires non-empty
    notes').
    """
    payload: Dict[str, Any] = {"decision": decision}
    if approved_level is not None:
        payload["approved_level"] = approved_level
    if notes is not None:
        payload["notes"] = notes
    return payload


def patch_options_approval_payload(
    *,
    version: int,
    requested_level: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD §3.2 (customer-driven patch action): carries an optional
    requested_level and the resource's version."""
    payload: Dict[str, Any] = {"version": version}
    if requested_level is not None:
        payload["requested_level"] = requested_level
    return payload


# ===========================================================================
# Orders — PRD §3.3
# ===========================================================================
def create_order_payload(
    *,
    account_id: str,
    symbol: str = "AAPL",
    instrument_type: str = "EQUITY",
    option_strategy: Optional[str] = None,
    side: str = "BUY",
    order_type: str = "LIMIT",
    quantity: int = 1,
    limit_price_cents: Optional[int] = None,
    stop_price_cents: Optional[int] = None,
) -> Dict[str, Any]:
    """PRD §3.3 inputs — account_id, symbol, instrument_type, optional
    option_strategy, side, order_type, quantity, conditionally-required
    limit_price_cents and stop_price_cents."""
    payload: Dict[str, Any] = {
        "account_id": account_id,
        "symbol": symbol,
        "instrument_type": instrument_type,
        "side": side,
        "order_type": order_type,
        "quantity": quantity,
    }
    # PRD §3.3: option_strategy required iff instrument_type==OPTION.
    if option_strategy is not None:
        payload["option_strategy"] = option_strategy
    # PRD §3.3: limit_price_cents required for LIMIT, STOP_LIMIT,
    # TAKE_PROFIT; stop_price_cents required for STOP, STOP_LIMIT.
    if limit_price_cents is not None:
        payload["limit_price_cents"] = limit_price_cents
    elif order_type in ("LIMIT", "STOP_LIMIT", "TAKE_PROFIT"):
        payload["limit_price_cents"] = (
            TEST_DEFAULTS["DEFAULT_LIMIT_PRICE_CENTS"]
        )
    if stop_price_cents is not None:
        payload["stop_price_cents"] = stop_price_cents
    elif order_type in ("STOP", "STOP_LIMIT"):
        payload["stop_price_cents"] = (
            TEST_DEFAULTS["DEFAULT_LIMIT_PRICE_CENTS"]
        )
    return payload


def fill_order_payload(*, execution_price_cents: int) -> Dict[str, Any]:
    """PRD §3.3: operator fill body carries execution_price_cents."""
    return {"execution_price_cents": execution_price_cents}


# ===========================================================================
# ACAT transfers — PRD §3.5
# ===========================================================================
def create_acat_transfer_payload(
    *,
    account_id: str,
    direction: str = "INBOUND",
    counterparty_brokerage: str = "Other Brokerage Inc",
    counterparty_account_number: Optional[str] = None,
    requested_value_cents: int = 100_000,
) -> Dict[str, Any]:
    """PRD §3.5 inputs — account_id, direction (INBOUND|OUTBOUND),
    counterparty_brokerage, counterparty_account_number,
    requested_value_cents (minimum 100)."""
    return {
        "account_id": account_id,
        "direction": direction,
        "counterparty_brokerage": counterparty_brokerage,
        "counterparty_account_number": (
            counterparty_account_number
            if counterparty_account_number is not None
            else f"ACCT-{random_suffix(6).upper()}"
        ),
        "requested_value_cents": requested_value_cents,
    }


def reject_acat_transfer_payload(*, reason: str) -> Dict[str, Any]:
    """PRD §3.5: compliance reject body carries a reason."""
    return {"reason": reason}


# ===========================================================================
# Account / PDT — PRD §3.4
# ===========================================================================
def pdt_reset_payload(*, equity_top_up_cents: int) -> Dict[str, Any]:
    """PRD §3.4: 'The customer calls the PDT-reset action, which carries
    an equity_top_up_cents amount'."""
    return {"equity_top_up_cents": equity_top_up_cents}


# ===========================================================================
# Clock / sweep — PRD §3.8
# ===========================================================================
def clock_advance_payload(*, seconds: int) -> Dict[str, Any]:
    """PRD §3.8: 'advances the server's logical clock by a number of
    seconds supplied in the request body'."""
    return {"seconds": seconds}


__all__ = [
    "random_suffix",
    "random_legal_name",
    "random_symbol",
    "today_utc",
    "iso_date_str",
    "years_ago_dob",
    "iso_now_utc",
    "create_customer_payload",
    "create_account_payload",
    "submit_kyc_payload",
    "kyc_decision_payload",
    "create_options_approval_payload",
    "decide_options_approval_payload",
    "patch_options_approval_payload",
    "create_order_payload",
    "fill_order_payload",
    "create_acat_transfer_payload",
    "reject_acat_transfer_payload",
    "pdt_reset_payload",
    "clock_advance_payload",
]
