"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema PRD §3 declares for that
request. Tests pass overrides for the values they want to control. Only
PRD-declared input fields are produced; computed/system fields are
intentionally omitted so the implementation cannot accidentally accept
them through these helpers.

PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
PRD §2.6: monetary fields are integer cents.
"""
from __future__ import annotations

import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Time helpers — PRD §2.4 ISO 8601 UTC with three fractional digits
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


def parse_iso(iso_ts: str) -> datetime:
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


def add_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)


# ---------------------------------------------------------------------------
# Random helpers
# ---------------------------------------------------------------------------
def random_suffix(length: int = 8) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits,
                                  k=length))


def random_email() -> str:
    return f"r_{random_suffix(6).lower()}@example.com"


def random_vin() -> str:
    """PRD §3.1: VIN is exactly 17 chars, A-Z and 0-9, globally unique."""
    return "".join(
        random.choices(string.ascii_uppercase + string.digits, k=17)
    )


# ---------------------------------------------------------------------------
# Park — PRD §3.1
# ---------------------------------------------------------------------------
def create_park_payload(
    name: Optional[str] = None,
    state_code: str = "CA",
    master_cpi_pct: float = 2.00,
    utility_apportionment_method: str = "EQUAL_SPLIT",
    billing_period_anchor_day: int = 1,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.1 declares the exact input set:
        name, state_code, master_cpi_pct,
        utility_apportionment_method, billing_period_anchor_day.
    """
    payload: Dict[str, Any] = {
        "name": name or f"{TEST_DEFAULTS['park_name_prefix']}_{random_suffix(6)}",
        "state_code": state_code,
        "master_cpi_pct": master_cpi_pct,
        "utility_apportionment_method": utility_apportionment_method,
        "billing_period_anchor_day": billing_period_anchor_day,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Lot — PRD §3.1
# ---------------------------------------------------------------------------
def create_lot_payload(
    lot_number: str,
    base_rent_cents: int = 100_000,
    sub_meter_reading_kwh: Optional[float] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.1: 'lot_number, base_rent_cents, and an optional
    sub_meter_reading_kwh'."""
    payload: Dict[str, Any] = {
        "lot_number": lot_number,
        "base_rent_cents": base_rent_cents,
    }
    if sub_meter_reading_kwh is not None:
        payload["sub_meter_reading_kwh"] = sub_meter_reading_kwh
    payload.update(overrides)
    return payload


def patch_lot_sub_meter_payload(
    sub_meter_reading_kwh: float,
    version: Optional[int] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.1: 'The only mutation a park manager can perform on an
    existing lot is updating sub_meter_reading_kwh (the supplied
    request body carries sub_meter_reading_kwh and an optional version).'
    """
    payload: Dict[str, Any] = {
        "sub_meter_reading_kwh": sub_meter_reading_kwh,
    }
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Home — PRD §3.1
# ---------------------------------------------------------------------------
def create_home_payload(
    lot_id: str,
    vin: Optional[str] = None,
    assessed_value_cents: int = 5_000_000,
    owner_resident_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.1: 'vin (exactly 17 chars...), the lot_id it will occupy,
    an assessed_value_cents greater than zero ..., and an
    owner_resident_id that is required only when the parent lot is in
    RESIDENT_OWNED mode and ignored otherwise.'"""
    payload: Dict[str, Any] = {
        "vin": vin or random_vin(),
        "lot_id": lot_id,
        "assessed_value_cents": assessed_value_cents,
    }
    if owner_resident_id is not None:
        payload["owner_resident_id"] = owner_resident_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Resident — PRD §3.1
# ---------------------------------------------------------------------------
def create_resident_payload(
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.1: 'A Resident is registered via full_name ... and email
    (RFC 5322 conformant and globally unique).'"""
    payload: Dict[str, Any] = {
        "full_name": full_name or f"{TEST_DEFAULTS['resident_name_prefix']} {random_suffix(4)}",
        "email": email or random_email(),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Lease — PRD §3.2
# ---------------------------------------------------------------------------
def create_lease_payload(
    resident_id: str,
    start_date: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.2: 'A ParkManager opens a new lease for a lot by
    submitting resident_id and start_date (a UTC midnight-aligned
    datetime indicating commencement).'"""
    if start_date is None:
        # Use today midnight UTC by default
        today = utcnow().replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        start_date = iso_utc(today)
    payload: Dict[str, Any] = {
        "resident_id": resident_id,
        "start_date": start_date,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# RentIncreaseNotice — PRD §3.5
# ---------------------------------------------------------------------------
def create_rent_increase_notice_payload(
    proposed_new_rent_cents: int,
    effective_on: str,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.5: 'The manager drafts a notice by submitting
    proposed_new_rent_cents ... and effective_on.'"""
    payload: Dict[str, Any] = {
        "proposed_new_rent_cents": proposed_new_rent_cents,
        "effective_on": effective_on,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# EvictionCase — PRD §3.6
# ---------------------------------------------------------------------------
def create_eviction_case_payload(
    violation_type: str,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.6: 'A ParkManager files an eviction case against a lease
    by submitting violation_type, one of NONPAYMENT, RULE_VIOLATION, or
    ILLEGAL_USE.'"""
    payload: Dict[str, Any] = {
        "violation_type": violation_type,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# HomeSaleTransfer — PRD §3.7
# ---------------------------------------------------------------------------
def create_home_sale_transfer_payload(
    home_id: str,
    seller_resident_id: str,
    buyer_resident_id: str,
    sale_price_cents: int = 6_000_000,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.7: 'submitting home_id, seller_resident_id (which must
    equal the home's current owner_resident_id), buyer_resident_id,
    and sale_price_cents (an integer greater than zero).'"""
    payload: Dict[str, Any] = {
        "home_id": home_id,
        "seller_resident_id": seller_resident_id,
        "buyer_resident_id": buyer_resident_id,
        "sale_price_cents": sale_price_cents,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ConversionRequest — PRD §3.8
# ---------------------------------------------------------------------------
def create_conversion_request_payload(
    prospective_buyer_resident_id: str,
    offer_price_cents: int,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.8: 'A ParkManager initiates the offer by submitting
    prospective_buyer_resident_id and offer_price_cents.'"""
    payload: Dict[str, Any] = {
        "prospective_buyer_resident_id": prospective_buyer_resident_id,
        "offer_price_cents": offer_price_cents,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock advance — PRD §2.11
# ---------------------------------------------------------------------------
def advance_clock_payload(seconds: int, **overrides) -> Dict[str, Any]:
    """PRD §2.11: 'A PlatformAdmin test-driving capability advances the
    clock by a supplied number of seconds.'"""
    payload: Dict[str, Any] = {"seconds": seconds}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Billing sweep — PRD §3.3
# ---------------------------------------------------------------------------
def sweep_billing_payload(
    park_id: str,
    billing_period_start: str,
    billing_period_end: str,
    master_total_cents: int,
    **overrides,
) -> Dict[str, Any]:
    """PRD §3.3: 'A PlatformAdmin invokes the billing sweep with a
    park_id selecting the park, a billing_period_start and
    billing_period_end ..., and the period's master_total_cents.'"""
    payload: Dict[str, Any] = {
        "park_id": park_id,
        "billing_period_start": billing_period_start,
        "billing_period_end": billing_period_end,
        "master_total_cents": master_total_cents,
    }
    payload.update(overrides)
    return payload


__all__ = [
    "iso_utc",
    "utcnow",
    "parse_iso",
    "add_days",
    "random_suffix",
    "random_email",
    "random_vin",
    "create_park_payload",
    "create_lot_payload",
    "patch_lot_sub_meter_payload",
    "create_home_payload",
    "create_resident_payload",
    "create_lease_payload",
    "create_rent_increase_notice_payload",
    "create_eviction_case_payload",
    "create_home_sale_transfer_payload",
    "create_conversion_request_payload",
    "advance_clock_payload",
    "sweep_billing_payload",
]
