"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body (PRD §3 narrative + §4 endpoint table). Tests pass
overrides for values they want to control. Only PRD-declared input
fields are produced; computed/system fields are intentionally omitted
so the implementation cannot accidentally accept them as inputs.

PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
PRD §2.7: monetary fields are USD with exactly 2 decimal places.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Timestamp / date helpers — PRD §2.4 format with three fractional
# digits.
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


def iso_instant_utc(year: int, month: int, day: int, hour: int = 12,
                    minute: int = 0, second: int = 0) -> str:
    """Deterministic ISO 8601 UTC instant with .000Z millis."""
    return iso_utc(datetime(year, month, day, hour, minute, second,
                            tzinfo=timezone.utc))


def iso_date(d: date) -> str:
    return d.isoformat()


def date_offset(d: date, *, days: int) -> date:
    return d + timedelta(days=days)


# ---------------------------------------------------------------------------
# Random helpers — keep names unique across tests when caller asks.
# ---------------------------------------------------------------------------
def random_suffix(length: int = 6) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits,
                                  k=length))


# ---------------------------------------------------------------------------
# Version body — PRD §2.5 optimistic concurrency
# ---------------------------------------------------------------------------
def version_body(version: Optional[int] = None) -> Dict[str, Any]:
    """PRD §2.5: 'Every PATCH endpoint on a resource that carries a
    version field accepts a version value in its request body.'"""
    return {"version": version} if version is not None else {}


# ---------------------------------------------------------------------------
# Clock — PRD §2.10
# ---------------------------------------------------------------------------
def clock_advance_payload(to_timestamp: str) -> Dict[str, Any]:
    """PRD §2.10: 'advances this clock to a supplied target instant
    carried as to_timestamp in the request body'."""
    return {"to_timestamp": to_timestamp}


# ---------------------------------------------------------------------------
# Trust — PRD §3.1
# ---------------------------------------------------------------------------
def create_trust_payload(
    *,
    name: Optional[str] = None,
    trust_type: str = "IRREVOCABLE",
    grantor_tax_status: str = "NON_GRANTOR",
    has_grantor_powers: bool = False,
    situs_state: Optional[str] = None,
    inception_date: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1: 'a payload containing the trust's legal name, the
    trust_type (either REVOCABLE or IRREVOCABLE), the
    grantor_tax_status (either GRANTOR or NON_GRANTOR), a
    has_grantor_powers boolean, a two-letter situs_state US state
    code, and the inception_date on which the trust instrument was
    executed.'
    """
    payload: Dict[str, Any] = {
        "name": name or f"{TEST_DEFAULTS['TRUST_NAME']} {random_suffix(4)}",
        "trust_type": trust_type,
        "grantor_tax_status": grantor_tax_status,
        "has_grantor_powers": has_grantor_powers,
        "situs_state": situs_state or TEST_DEFAULTS["SITUS_STATE"],
        "inception_date": inception_date or TEST_DEFAULTS["INCEPTION_DATE"],
    }
    payload.update(overrides)
    return payload


def patch_trust_payload(
    *,
    name: Optional[str] = None,
    situs_state: Optional[str] = None,
    trust_type: Optional[str] = None,
    grantor_tax_status: Optional[str] = None,
    has_grantor_powers: Optional[bool] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.1 / §4: PATCH trust fields. trust_type and
    grantor_tax_status are only mutable while status=DRAFT."""
    body: Dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if situs_state is not None:
        body["situs_state"] = situs_state
    if trust_type is not None:
        body["trust_type"] = trust_type
    if grantor_tax_status is not None:
        body["grantor_tax_status"] = grantor_tax_status
    if has_grantor_powers is not None:
        body["has_grantor_powers"] = has_grantor_powers
    if version is not None:
        body["version"] = version
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# Trustee — PRD §3.2
# ---------------------------------------------------------------------------
def create_trustee_payload(
    *,
    user_id: Optional[str] = None,
    full_name: Optional[str] = None,
    is_primary: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2: 'a payload containing the trustee's user_id (the
    opaque platform identifier of the natural person who will act as
    trustee), their legal full_name, and a boolean is_primary flag.'
    """
    payload: Dict[str, Any] = {
        "user_id": user_id or f"trustee-user-{random_suffix(8)}",
        "full_name": full_name or TEST_DEFAULTS["TRUSTEE_FULL_NAME"],
        "is_primary": is_primary,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Beneficiary — PRD §3.2
# ---------------------------------------------------------------------------
def create_beneficiary_payload(
    *,
    full_name: Optional[str] = None,
    relation_class: str = "CHILD",
    beneficiary_class: str = "INCOME_AND_REMAINDER",
    distribution_tier: str = "TIER_1",
    birth_date: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2: 'a payload containing the beneficiary's full_name,
    the relation_class (SPOUSE, CHILD, GRANDCHILD, OTHER_LINEAL, or
    NON_LINEAL), the beneficiary_class (INCOME, REMAINDER, or
    INCOME_AND_REMAINDER), the distribution_tier (TIER_1 for
    mandatory income distributees or TIER_2 for discretionary), and
    the birth_date.'
    """
    payload: Dict[str, Any] = {
        "full_name": full_name or TEST_DEFAULTS["BENEFICIARY_NAME"],
        "relation_class": relation_class,
        "beneficiary_class": beneficiary_class,
        "distribution_tier": distribution_tier,
        "birth_date": birth_date or TEST_DEFAULTS["BENEFICIARY_BIRTH_DATE"],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Asset — PRD §3.2
# ---------------------------------------------------------------------------
def create_asset_payload(
    *,
    description: Optional[str] = None,
    asset_class: str = "CASH",
    book_value: Optional[float] = None,
    classification: str = "PRINCIPAL",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.2: 'The request body carries a description string, an
    asset_class (CASH, EQUITY, BOND, REAL_ESTATE, or OTHER), a
    book_value in USD with two decimal places, and a classification
    of either PRINCIPAL or INCOME.'
    """
    payload: Dict[str, Any] = {
        "description": description or "Test Asset",
        "asset_class": asset_class,
        "book_value": (
            book_value if book_value is not None
            else TEST_DEFAULTS["ASSET_BOOK_VALUE"]
        ),
        "classification": classification,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Transaction — PRD §3.3
# ---------------------------------------------------------------------------
def create_transaction_payload(
    *,
    txn_type: str = "INCOME_ORDINARY",
    amount: Optional[float] = None,
    transaction_date: Optional[str] = None,
    principal_or_income: str = "INCOME",
    description: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.3: 'Each Transaction submission carries a txn_type ...,
    a positive amount in USD with two decimal places ... a
    transaction_date, a principal_or_income accounting classification
    (either PRINCIPAL or INCOME), and a free-text description memo.'
    """
    payload: Dict[str, Any] = {
        "txn_type": txn_type,
        "amount": (
            amount if amount is not None
            else TEST_DEFAULTS["ORDINARY_INCOME"]
        ),
        "transaction_date": (
            transaction_date
            or iso_instant_utc(TEST_DEFAULTS["INCEPTION_YEAR"], 6, 1)
        ),
        "principal_or_income": principal_or_income,
        "description": description or "Test transaction",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Distribution — PRD §3.4
# ---------------------------------------------------------------------------
def create_distribution_payload(
    *,
    beneficiary_id: str,
    scheduled_date: Optional[str] = None,
    amount_principal: float = 0.0,
    amount_income: float = 0.0,
    distribution_type: str = "DISCRETIONARY",
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.4: 'a request body containing the recipient's
    beneficiary_id, a scheduled_date, an amount_principal (USD, two
    decimal places, not less than zero), an amount_income (USD, two
    decimal places, not less than zero), and a distribution_type of
    MANDATORY ..., DISCRETIONARY, or TERMINATING.'
    """
    payload: Dict[str, Any] = {
        "beneficiary_id": beneficiary_id,
        "scheduled_date": (
            scheduled_date
            or iso_instant_utc(TEST_DEFAULTS["INCEPTION_YEAR"], 6, 15)
        ),
        "amount_principal": amount_principal,
        "amount_income": amount_income,
        "distribution_type": distribution_type,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Tax year — PRD §3.5
# ---------------------------------------------------------------------------
def create_tax_year_payload(
    *,
    calendar_year: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """PRD §3.5: 'A Trustee or TaxPreparer opens a TaxYear by
    supplying its four-digit calendar_year.'"""
    payload: Dict[str, Any] = {
        "calendar_year": (
            calendar_year if calendar_year is not None
            else TEST_DEFAULTS["INCEPTION_YEAR"]
        ),
    }
    payload.update(overrides)
    return payload


__all__ = [
    "iso_utc",
    "utcnow",
    "iso_now",
    "iso_instant_utc",
    "iso_date",
    "date_offset",
    "random_suffix",
    "version_body",
    "clock_advance_payload",
    "create_trust_payload",
    "patch_trust_payload",
    "create_trustee_payload",
    "create_beneficiary_payload",
    "create_asset_payload",
    "create_transaction_payload",
    "create_distribution_payload",
    "create_tax_year_payload",
]
