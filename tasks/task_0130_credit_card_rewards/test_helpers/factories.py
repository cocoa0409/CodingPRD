"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body (PRD §3 narrative + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed/system fields are intentionally omitted so
the implementation cannot accidentally accept them as inputs.

PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
PRD §2.8: monetary fields are integer cents; points are integers.
"""
from __future__ import annotations

import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

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


def iso_instant_utc(year: int, month: int, day: int, hour: int = 0,
                    minute: int = 0, second: int = 0,
                    millis: int = 0) -> str:
    """Build an ISO 8601 UTC instant. millis is in 0..999."""
    base = datetime(year, month, day, hour, minute, second,
                    tzinfo=timezone.utc)
    return iso_utc(base + timedelta(milliseconds=millis))


def iso_offset(*, days: int = 0, hours: int = 0, minutes: int = 0,
               seconds: int = 0, millis: int = 0,
               base: Optional[datetime] = None) -> str:
    base = base or utcnow()
    return iso_utc(base + timedelta(
        days=days, hours=hours, minutes=minutes, seconds=seconds,
        milliseconds=millis,
    ))


def parse_iso(iso_ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp produced by iso_utc."""
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# Random-id helpers — for unique email/code generation.
# ---------------------------------------------------------------------------
# PRD §3.2 limits cashback category codes to "uppercase A-Z plus
# underscore" — no digits allowed there. PRD §3.3 permits digits in
# partner codes ("uppercase A-Z, digits, and underscore"). We keep two
# distinct alphabets so each factory respects its rule.
_LETTERS = string.ascii_uppercase
_ALPHANUM = string.ascii_uppercase + string.digits


def random_suffix(n: int = 8) -> str:
    """Uppercase-alphanumeric suffix; used by partner codes and the
    lowercase-translated email helper. Not used for cashback category
    codes (those forbid digits — see random_category_code)."""
    return "".join(random.choices(_ALPHANUM, k=n))


def _random_letters(n: int = 6) -> str:
    """Uppercase-letters-only suffix — PRD §3.2 cashback category
    codes."""
    return "".join(random.choices(_LETTERS, k=n))


def random_email() -> str:
    """PRD §3.1: 'email (a lowercase, unique RFC 5322 address used for
    login lookup)'.
    """
    return f"cardholder-{random_suffix(8).lower()}@example.test"


def random_category_code(prefix: str = "CAT") -> str:
    """PRD §3.2: 'a code (uppercase A-Z plus underscore, unique across
    the catalogue, for example GROCERY, GAS, DINING, or BASE)'.

    Output: only uppercase letters and underscores — no digits.
    """
    return f"{prefix}_{_random_letters(6)}"


def random_partner_code(prefix: str = "AIR") -> str:
    """PRD §3.3: 'a unique code (uppercase A-Z, digits, and underscore,
    for example AIR_BLUE or HOTEL_PINE)'.
    """
    return f"{prefix}_{random_suffix(6)}"


# ===========================================================================
# Cardholder — PRD §3.1
# ===========================================================================
def create_cardholder_payload(
    *,
    email: Optional[str] = None,
    display_name: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /cardholders — PlatformAdmin only.

    PRD §3.1: "A PlatformAdmin provisions a Cardholder by supplying the
    cardholder's email (a lowercase, unique RFC 5322 address used for
    login lookup) and display_name (the human-readable name printed on
    receipts and statements)."
    """
    payload: Dict[str, Any] = {
        "email": email if email is not None else random_email(),
        "display_name": (
            display_name if display_name is not None
            else f"Test Cardholder {random_suffix(4)}"
        ),
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# Account — PRD §3.1
# ===========================================================================
def create_account_payload(
    *,
    cardholder_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /accounts — PlatformAdmin only.

    PRD §3.1: "With a cardholder on file, the same operator opens an
    Account by supplying the cardholder_id."
    """
    payload: Dict[str, Any] = {"cardholder_id": cardholder_id}
    payload.update(overrides)
    return payload


# ===========================================================================
# CashbackCategory — PRD §3.2
# ===========================================================================
def create_cashback_category_payload(
    *,
    code: Optional[str] = None,
    category_type: str = "FIXED_BONUS",
    base_rate_bps: int = 500,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /cashback-categories — PlatformAdmin only.

    PRD §3.2: "A PlatformAdmin registers a CashbackCategory by supplying
    a code (uppercase A-Z plus underscore, unique across the catalogue,
    for example GROCERY, GAS, DINING, or BASE), a category_type drawn
    from BASELINE, FIXED_BONUS, and ROTATING_QUARTERLY, and an integer
    base_rate_bps between zero and ten thousand inclusive that expresses
    the earn rate in basis points".

    Note requires_activation is intentionally omitted: PRD §3.2 says
    "the server sets requires_activation to true if and only if
    category_type is ROTATING_QUARTERLY; the field is therefore derived,
    not client-supplied."
    """
    payload: Dict[str, Any] = {
        "code": code if code is not None else random_category_code(),
        "category_type": category_type,
        "base_rate_bps": base_rate_bps,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# TransferPartner — PRD §3.3
# ===========================================================================
def create_transfer_partner_payload(
    *,
    code: Optional[str] = None,
    partner_type: str = "AIRLINE",
    conversion_ratio_points_per_unit: int = 2,
    min_transfer_increment: int = 1000,
    is_active: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /transfer-partners — PlatformAdmin only.

    PRD §3.3: "A PlatformAdmin registers a TransferPartner with a unique
    code ..., a partner_type of AIRLINE or HOTEL, an integer
    conversion_ratio_points_per_unit of at least one expressing how many
    cardholder points are required per one partner-currency unit ..., an
    integer min_transfer_increment of at least one ..., and an optional
    is_active boolean defaulting to true".
    """
    payload: Dict[str, Any] = {
        "code": code if code is not None else random_partner_code(),
        "partner_type": partner_type,
        "conversion_ratio_points_per_unit":
            conversion_ratio_points_per_unit,
        "min_transfer_increment": min_transfer_increment,
    }
    if is_active is not None:
        payload["is_active"] = is_active
    payload.update(overrides)
    return payload


# ===========================================================================
# Transaction — PRD §3.4
# ===========================================================================
def create_purchase_payload(
    *,
    account_id: str,
    category_id: str,
    amount_cents: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /transactions for PURCHASE — PRD §3.4.

    PRD §3.4: "A Cardholder posts a transaction against their own
    account by supplying account_id, category_id, txn_type (one of
    PURCHASE or REFUND), an amount_cents of at least one ..., and — only
    for refunds — an original_transaction_id naming the purchase being
    reversed."
    """
    payload: Dict[str, Any] = {
        "account_id": account_id,
        "category_id": category_id,
        "txn_type": "PURCHASE",
        "amount_cents": amount_cents,
    }
    payload.update(overrides)
    return payload


def create_refund_payload(
    *,
    account_id: str,
    category_id: str,
    amount_cents: int,
    original_transaction_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /transactions for REFUND — PRD §3.4.

    PRD §3.4 names refund-specific check: "Refunds carry an additional
    pair of checks: the referenced original must have txn_type equal to
    PURCHASE and must belong to the same account_id".
    """
    payload: Dict[str, Any] = {
        "account_id": account_id,
        "category_id": category_id,
        "txn_type": "REFUND",
        "amount_cents": amount_cents,
        "original_transaction_id": original_transaction_id,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# QuarterlyActivation — PRD §3.2
# ===========================================================================
def create_activation_payload(
    *,
    category_id: str,
    quarter_label: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /accounts/{account_id}/activate-category — Cardholder.

    PRD §3.2: "The request supplies category_id and quarter_label".
    quarter_label format per PRD §2.12: "four digits then the letter Q
    then a digit one through four, for example 2026Q2".
    """
    payload: Dict[str, Any] = {
        "category_id": category_id,
        "quarter_label": quarter_label,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# PointsTransfer — PRD §3.7
# ===========================================================================
def create_points_transfer_payload(
    *,
    account_id: str,
    partner_id: str,
    requested_partner_units: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /points-transfers — Cardholder.

    PRD §3.7: "A Cardholder initiates a points transfer by supplying
    account_id, partner_id, and requested_partner_units — the number of
    partner-currency units (miles, hotel points) to deliver."
    """
    payload: Dict[str, Any] = {
        "account_id": account_id,
        "partner_id": partner_id,
        "requested_partner_units": requested_partner_units,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# StatementCredit — PRD §3.6
# ===========================================================================
def create_points_first_redemption_payload(
    *,
    account_id: str,
    requested_points: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /statement-credits in POINTS_FIRST mode — PRD §3.6.

    PRD §3.6: "POINTS_FIRST requires requested_points to be present and
    requested_amount_cents to be absent".
    """
    payload: Dict[str, Any] = {
        "account_id": account_id,
        "redemption_mode": "POINTS_FIRST",
        "requested_points": requested_points,
    }
    payload.update(overrides)
    return payload


def create_amount_first_redemption_payload(
    *,
    account_id: str,
    requested_amount_cents: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /statement-credits in AMOUNT_FIRST mode — PRD §3.6.

    PRD §3.6: "AMOUNT_FIRST requires requested_amount_cents to be
    present and requested_points to be absent".
    """
    payload: Dict[str, Any] = {
        "account_id": account_id,
        "redemption_mode": "AMOUNT_FIRST",
        "requested_amount_cents": requested_amount_cents,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# Clock — PRD §3.8
# ===========================================================================
def clock_advance_payload(*, to_timestamp: str,
                          **overrides: Any) -> Dict[str, Any]:
    """POST /_clock/advance payload.

    PRD §3.8: "The clock capability accepts a single to_timestamp and
    advances the simulated clock to that ISO 8601 instant".
    """
    payload: Dict[str, Any] = {"to_timestamp": to_timestamp}
    payload.update(overrides)
    return payload


__all__ = [
    # Timestamp helpers
    "iso_utc",
    "utcnow",
    "iso_now",
    "iso_instant_utc",
    "iso_offset",
    "parse_iso",
    # Random helpers
    "random_suffix",
    "random_email",
    "random_category_code",
    "random_partner_code",
    # Payload factories
    "create_cardholder_payload",
    "create_account_payload",
    "create_cashback_category_payload",
    "create_transfer_partner_payload",
    "create_purchase_payload",
    "create_refund_payload",
    "create_activation_payload",
    "create_points_transfer_payload",
    "create_points_first_redemption_payload",
    "create_amount_first_redemption_payload",
    "clock_advance_payload",
]
