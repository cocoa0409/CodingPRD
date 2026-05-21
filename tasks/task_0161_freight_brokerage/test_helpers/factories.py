"""Payload factories — one per entity, input fields only.

Each factory returns a dict ready to be sent as the JSON request body
for the corresponding create endpoint. Defaults are chosen so that a
factory called with no overrides produces a request that satisfies the
PRD's positive-path validation rules; tests pass overrides to exercise
specific edge cases.

ISO 8601 helpers (`iso_utc`, `add_seconds`, `add_minutes`, `add_days`)
emit timestamps with three fractional digits, matching PRD §2.4.
"""
from __future__ import annotations

import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .constants import (
    DEFAULT_DETENTION_FREE_MINUTES,
    DEFAULT_DETENTION_RATE_CENTS_PER_15MIN,
    TEST_DEFAULTS,
)


# ---------------------------------------------------------------------------
# ISO 8601 helpers
# ---------------------------------------------------------------------------
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime) -> str:
    """Render `dt` as ISO 8601 UTC with milliseconds and trailing Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    # Truncate microseconds to milliseconds.
    millis = dt.microsecond // 1000
    return dt.strftime(f"%Y-%m-%dT%H:%M:%S.{millis:03d}Z")


def iso_now() -> str:
    return iso_utc(utcnow())


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 string (with trailing Z or offset) into UTC."""
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def add_seconds(dt: datetime, seconds: int) -> datetime:
    return dt + timedelta(seconds=seconds)


def add_minutes(dt: datetime, minutes: int) -> datetime:
    return dt + timedelta(minutes=minutes)


def add_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)


# ---------------------------------------------------------------------------
# Unique identifiers — keep MC#/USDOT uniqueness per brokerage stable.
# ---------------------------------------------------------------------------
def random_suffix(length: int = 8) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits,
                                  k=length))


def unique_mc_number() -> str:
    return f"MC{random.randint(100_000, 999_999)}{random_suffix(4)}"


def unique_usdot_number() -> str:
    return f"USDOT{random.randint(1_000_000, 9_999_999)}{random_suffix(4)}"


def unique_zip(prefix: int = 10000) -> str:
    """Generate a 5-digit ZIP-like integer string."""
    return f"{prefix + random.randint(0, 89_999)}"


# ---------------------------------------------------------------------------
# Brokerage — PRD §3.1
# ---------------------------------------------------------------------------
def create_brokerage_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": TEST_DEFAULTS["BROKERAGE_NAME"],
        "mc_number": f"MC{random.randint(100_000, 999_999)}",
        "factoring_reserve_pct": TEST_DEFAULTS["FACTORING_RESERVE_PCT"],
        "detention_free_minutes": DEFAULT_DETENTION_FREE_MINUTES,
        "detention_rate_cents_per_15min": (
            DEFAULT_DETENTION_RATE_CENTS_PER_15MIN
        ),
    }
    payload.update(overrides)
    return payload


def clock_advance_payload(to_iso: str) -> Dict[str, Any]:
    return {"to_iso": to_iso}


# ---------------------------------------------------------------------------
# Shipper — PRD §3.2
# ---------------------------------------------------------------------------
def create_shipper_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "company_name": TEST_DEFAULTS["SHIPPER_NAME"],
        "smartway_required": False,
        "credit_limit_cents": TEST_DEFAULTS["SHIPPER_CREDIT_LIMIT"],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Carrier — PRD §3.3
# ---------------------------------------------------------------------------
def create_carrier_payload(**overrides: Any) -> Dict[str, Any]:
    insurance_default = iso_utc(add_days(utcnow(), 365))
    payload: Dict[str, Any] = {
        "legal_name": TEST_DEFAULTS["CARRIER_NAME"],
        "mc_number": unique_mc_number(),
        "usdot_number": unique_usdot_number(),
        "insurance_expires_on": insurance_default,
        "smartway_certified": False,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# RateContract — PRD §3.4
# ---------------------------------------------------------------------------
def create_rate_contract_payload(
    shipper_id: str,
    lane_origin_zip: str = "10000",
    lane_destination_zip: str = "20000",
    equipment_type: str = "DRY_VAN",
    flat_rate_cents: int = 50_000,
    effective_from: Optional[str] = None,
    effective_to: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    if effective_from is None:
        effective_from = iso_utc(add_days(utcnow(), -1))
    if effective_to is None:
        effective_to = iso_utc(add_days(utcnow(), 30))
    payload: Dict[str, Any] = {
        "shipper_id": shipper_id,
        "lane_origin_zip": lane_origin_zip,
        "lane_destination_zip": lane_destination_zip,
        "equipment_type": equipment_type,
        "flat_rate_cents": flat_rate_cents,
        "effective_from": effective_from,
        "effective_to": effective_to,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# QuoteRequest — PRD §3.5
# ---------------------------------------------------------------------------
def create_quote_request_payload(
    origin_zip: str = "10001",
    destination_zip: str = "20002",
    equipment_type: str = "DRY_VAN",
    pickup_window_start: Optional[str] = None,
    pickup_window_end: Optional[str] = None,
    rate_contract_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    if pickup_window_start is None:
        pickup_window_start = iso_utc(add_days(utcnow(), 1))
    if pickup_window_end is None:
        pickup_window_end = iso_utc(add_days(utcnow(), 7))
    payload: Dict[str, Any] = {
        "origin_zip": origin_zip,
        "destination_zip": destination_zip,
        "equipment_type": equipment_type,
        "pickup_window_start": pickup_window_start,
        "pickup_window_end": pickup_window_end,
    }
    if rate_contract_id is not None:
        payload["rate_contract_id"] = rate_contract_id
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Load tender — PRD §3.6
# ---------------------------------------------------------------------------
def create_load_payload(quote_request_id: str, carrier_id: str,
                        **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "quote_request_id": quote_request_id,
        "carrier_id": carrier_id,
    }
    payload.update(overrides)
    return payload


def deliver_load_payload(actual_arrive_at: str, actual_depart_at: str,
                         **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "actual_arrive_at": actual_arrive_at,
        "actual_depart_at": actual_depart_at,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# AccessorialCharge — PRD §3.7
# ---------------------------------------------------------------------------
def create_accessorial_charge_payload(
    charge_type: str = "LUMPER",
    amount_cents: int = 5_000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "charge_type": charge_type,
        "amount_cents": amount_cents,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# DisputeClaim — PRD §3.9
# ---------------------------------------------------------------------------
def create_dispute_claim_payload(
    claim_type: str = "DAMAGE",
    claimed_cents: int = 1_000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "claim_type": claim_type,
        "claimed_cents": claimed_cents,
    }
    payload.update(overrides)
    return payload


def counter_dispute_claim_payload(counter_offer_cents: int,
                                  **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"counter_offer_cents": counter_offer_cents}
    payload.update(overrides)
    return payload


def resolve_dispute_claim_payload(settled_credit_cents: int,
                                  **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"settled_credit_cents": settled_credit_cents}
    payload.update(overrides)
    return payload


__all__ = [
    # ISO helpers
    "utcnow", "iso_utc", "iso_now", "parse_iso",
    "add_seconds", "add_minutes", "add_days",
    # Unique generators
    "random_suffix", "unique_mc_number", "unique_usdot_number",
    "unique_zip",
    # Factories
    "create_brokerage_payload", "clock_advance_payload",
    "create_shipper_payload",
    "create_carrier_payload",
    "create_rate_contract_payload",
    "create_quote_request_payload",
    "create_load_payload",
    "deliver_load_payload",
    "create_accessorial_charge_payload",
    "create_dispute_claim_payload",
    "counter_dispute_claim_payload",
    "resolve_dispute_claim_payload",
]
