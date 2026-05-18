"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body (PRD §3 narrative + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed/system fields are intentionally omitted
so the implementation cannot accidentally accept them as inputs.

PRD §2.7: Money values are integer cents. Timestamps are ISO 8601
strings with three fractional digits.
"""
from __future__ import annotations

import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .constants import (
    TEST_DEFAULTS,
)


# ---------------------------------------------------------------------------
# Random / id helpers
# ---------------------------------------------------------------------------
def random_suffix(n: int = 8) -> str:
    return "".join(
        random.choices(string.ascii_lowercase + string.digits, k=n),
    )


def random_full_name(prefix: str = "Test Person") -> str:
    return f"{prefix} {random_suffix(6)}"


def random_license_number() -> str:
    # Use a wide alpha+digit prefix to avoid collisions across tests.
    return f"LIC-{random_suffix(10).upper()}"


def random_serial_number() -> str:
    return f"SN-{random_suffix(10).upper()}"


def random_address() -> str:
    return f"{random.randint(100, 9999)} {random_suffix(8).title()} St"


# ---------------------------------------------------------------------------
# Time helpers — PRD §2.7
# ---------------------------------------------------------------------------
def iso_now_utc() -> str:
    """PRD §2.7 ISO 8601 UTC timestamp with three fractional digits."""
    dt = datetime.now(tz=timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def iso_in_future(seconds: int = 3600) -> str:
    dt = datetime.now(tz=timezone.utc) + timedelta(seconds=seconds)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def iso_in_past(seconds: int = 3600) -> str:
    dt = datetime.now(tz=timezone.utc) - timedelta(seconds=seconds)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def iso_from_now(*, days: int = 0, hours: int = 0, minutes: int = 0,
                 seconds: int = 0) -> str:
    delta = timedelta(days=days, hours=hours, minutes=minutes,
                      seconds=seconds)
    dt = datetime.now(tz=timezone.utc) + delta
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def iso_at(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


# ===========================================================================
# Agent — PRD §3.1
# ===========================================================================
def create_agent_payload(
    *,
    full_name: Optional[str] = None,
    brokerage_name: Optional[str] = None,
    agent_role: str = "LISTING_AGENT",
    license_number: Optional[str] = None,
    brokerage_split_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """PRD §3.1: full_name, brokerage_name, agent_role
    (LISTING_AGENT/BUYER_AGENT/DUAL_AGENT), license_number (unique
    across active agents), and optional brokerage_split_pct.
    """
    payload: Dict[str, Any] = {
        "full_name": full_name or random_full_name("Agent"),
        "brokerage_name": brokerage_name or f"Brokerage {random_suffix(4)}",
        "agent_role": agent_role,
        "license_number": license_number or random_license_number(),
    }
    if brokerage_split_pct is not None:
        payload["brokerage_split_pct"] = brokerage_split_pct
    return payload


def patch_agent_payload(
    *,
    version: int,
    brokerage_split_pct: Optional[float] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    """PRD §3.1: editable fields are brokerage_split_pct and status;
    PRD §2.6: PATCH consumes a `version` field for OCC."""
    payload: Dict[str, Any] = {"version": version}
    if brokerage_split_pct is not None:
        payload["brokerage_split_pct"] = brokerage_split_pct
    if status is not None:
        payload["status"] = status
    return payload


# ===========================================================================
# Listing — PRD §3.2
# ===========================================================================
def create_listing_payload(
    *,
    listing_agent_id: str,
    address_line: Optional[str] = None,
    zip_code: Optional[str] = None,
    list_price_cents: Optional[int] = None,
    bedrooms: Optional[int] = None,
    bathrooms: Optional[float] = None,
    features: Optional[List[str]] = None,
    co_op_pct: Optional[float] = None,
    total_commission_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """PRD §3.2 inputs. Caller MUST pass listing_agent_id — PRD §3.2
    requires it to equal X-User-ID."""
    return {
        "listing_agent_id": listing_agent_id,
        "address_line": address_line or random_address(),
        "zip_code": zip_code or TEST_DEFAULTS["ZIP_CODE"],
        "list_price_cents": (
            list_price_cents if list_price_cents is not None
            else TEST_DEFAULTS["LIST_PRICE_CENTS"]
        ),
        "bedrooms": bedrooms if bedrooms is not None else TEST_DEFAULTS["BEDROOMS"],
        "bathrooms": bathrooms if bathrooms is not None else TEST_DEFAULTS["BATHROOMS"],
        "features": features if features is not None else ["POOL", "GARAGE"],
        "co_op_pct": (
            co_op_pct if co_op_pct is not None
            else TEST_DEFAULTS["CO_OP_PCT"]
        ),
        "total_commission_pct": (
            total_commission_pct if total_commission_pct is not None
            else TEST_DEFAULTS["TOTAL_COMMISSION_PCT"]
        ),
    }


def patch_listing_payload(
    *,
    version: int,
    list_price_cents: Optional[int] = None,
    features: Optional[List[str]] = None,
    co_op_pct: Optional[float] = None,
    total_commission_pct: Optional[float] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"version": version}
    if list_price_cents is not None:
        payload["list_price_cents"] = list_price_cents
    if features is not None:
        payload["features"] = features
    if co_op_pct is not None:
        payload["co_op_pct"] = co_op_pct
    if total_commission_pct is not None:
        payload["total_commission_pct"] = total_commission_pct
    return payload


def withdraw_listing_payload(*, version: int) -> Dict[str, Any]:
    return {"version": version}


def close_listing_payload(*, version: int) -> Dict[str, Any]:
    return {"version": version}


# ===========================================================================
# Buyer — PRD §3.3
# ===========================================================================
def create_buyer_payload(
    *,
    buyer_agent_id: str,
    full_name: Optional[str] = None,
    max_price_cents: int = 60_000_000,
    min_price_cents: int = 40_000_000,
    min_bedrooms: int = 2,
    min_bathrooms: float = 1.0,
    desired_zips: Optional[List[str]] = None,
    desired_features: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """PRD §3.3 inputs. Caller MUST pass buyer_agent_id — PRD §3.3
    requires it to equal X-User-ID."""
    return {
        "buyer_agent_id": buyer_agent_id,
        "full_name": full_name or random_full_name("Buyer"),
        "max_price_cents": max_price_cents,
        "min_price_cents": min_price_cents,
        "min_bedrooms": min_bedrooms,
        "min_bathrooms": min_bathrooms,
        "desired_zips": (
            desired_zips if desired_zips is not None
            else [TEST_DEFAULTS["ZIP_CODE"]]
        ),
        "desired_features": (
            desired_features if desired_features is not None else []
        ),
    }


def patch_buyer_payload(
    *,
    version: int,
    max_price_cents: Optional[int] = None,
    min_price_cents: Optional[int] = None,
    min_bedrooms: Optional[int] = None,
    min_bathrooms: Optional[float] = None,
    desired_zips: Optional[List[str]] = None,
    desired_features: Optional[List[str]] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"version": version}
    if max_price_cents is not None:
        payload["max_price_cents"] = max_price_cents
    if min_price_cents is not None:
        payload["min_price_cents"] = min_price_cents
    if min_bedrooms is not None:
        payload["min_bedrooms"] = min_bedrooms
    if min_bathrooms is not None:
        payload["min_bathrooms"] = min_bathrooms
    if desired_zips is not None:
        payload["desired_zips"] = desired_zips
    if desired_features is not None:
        payload["desired_features"] = desired_features
    if status is not None:
        payload["status"] = status
    return payload


# ===========================================================================
# Lockbox — PRD §3.5
# ===========================================================================
def create_lockbox_payload(
    *,
    serial_number: Optional[str] = None,
) -> Dict[str, Any]:
    return {"serial_number": serial_number or random_serial_number()}


# ===========================================================================
# Showing — PRD §3.5
# ===========================================================================
def request_showing_payload(
    *,
    buyer_agent_id: str,
    buyer_id: str,
    start_at: Optional[str] = None,
    end_at: Optional[str] = None,
    duration_minutes: int = 60,
    offset_seconds: int = 3600,
) -> Dict[str, Any]:
    """PRD §3.5: BuyerAgent supplies buyer_agent_id, buyer_id, start_at,
    end_at. PRD §3.5 requires `buyer_agent_id` to equal X-User-ID for
    ownership."""
    if start_at is None:
        start_at = iso_in_future(offset_seconds)
    if end_at is None:
        # Derive from start_at and duration.
        start_dt = datetime.fromisoformat(
            start_at.replace("Z", "+00:00"),
        )
        end_dt = start_dt + timedelta(minutes=duration_minutes)
        end_at = iso_at(end_dt)
    return {
        "buyer_agent_id": buyer_agent_id,
        "buyer_id": buyer_id,
        "start_at": start_at,
        "end_at": end_at,
    }


# ===========================================================================
# Offers — PRD §3.6
# ===========================================================================
def submit_offer_payload(
    *,
    buyer_id: str,
    offer_price_cents: int = 50_000_000,
    earnest_money_cents: int = 1_000_000,
    estimated_seller_concessions_cents: Optional[int] = None,
    expires_at: Optional[str] = None,
    parent_counter_id: Optional[str] = None,
    offset_seconds: int = 24 * 3600,
) -> Dict[str, Any]:
    """PRD §3.6 inputs for POST /listings/{id}/offers."""
    payload: Dict[str, Any] = {
        "buyer_id": buyer_id,
        "offer_price_cents": offer_price_cents,
        "earnest_money_cents": earnest_money_cents,
        "expires_at": expires_at or iso_in_future(offset_seconds),
    }
    if estimated_seller_concessions_cents is not None:
        payload["estimated_seller_concessions_cents"] = (
            estimated_seller_concessions_cents
        )
    if parent_counter_id is not None:
        payload["parent_counter_id"] = parent_counter_id
    return payload


def counter_offer_payload(
    *,
    counter_price_cents: int = 51_000_000,
    counter_concessions_cents: int = 0,
    counter_expires_at: Optional[str] = None,
    offset_seconds: int = 12 * 3600,
) -> Dict[str, Any]:
    """PRD §3.6 inputs for POST /listings/{id}/offers/{id}/counter."""
    return {
        "counter_price_cents": counter_price_cents,
        "counter_concessions_cents": counter_concessions_cents,
        "counter_expires_at": counter_expires_at or iso_in_future(offset_seconds),
    }


def rebound_offer_payload(
    *,
    offer_price_cents: int = 50_000_000,
    earnest_money_cents: int = 1_000_000,
    estimated_seller_concessions_cents: Optional[int] = None,
    expires_at: Optional[str] = None,
    offset_seconds: int = 12 * 3600,
) -> Dict[str, Any]:
    """PRD §3.6 inputs for POST /listings/{id}/offers/{id}/rebound."""
    payload: Dict[str, Any] = {
        "offer_price_cents": offer_price_cents,
        "earnest_money_cents": earnest_money_cents,
        "expires_at": expires_at or iso_in_future(offset_seconds),
    }
    if estimated_seller_concessions_cents is not None:
        payload["estimated_seller_concessions_cents"] = (
            estimated_seller_concessions_cents
        )
    return payload


# ===========================================================================
# Contingency — PRD §3.7
# ===========================================================================
def create_contingency_payload(
    *,
    offer_id: str,
    kind: str = "INSPECTION",
    deadline_at: Optional[str] = None,
    offset_seconds: int = 7 * 24 * 3600,
) -> Dict[str, Any]:
    """PRD §3.7 inputs. PRD §3.7 requires deadline_at strictly after
    the accepted offer's acceptance time and strictly in the future at
    the moment of creation."""
    return {
        "offer_id": offer_id,
        "kind": kind,
        "deadline_at": deadline_at or iso_in_future(offset_seconds),
    }


# ===========================================================================
# Clock advance — PRD §3.9
# ===========================================================================
def clock_advance_payload(*, to: str) -> Dict[str, Any]:
    return {"to": to}


__all__ = [
    "random_suffix",
    "random_full_name",
    "random_license_number",
    "random_serial_number",
    "random_address",
    "iso_now_utc",
    "iso_in_future",
    "iso_in_past",
    "iso_from_now",
    "iso_at",
    "create_agent_payload",
    "patch_agent_payload",
    "create_listing_payload",
    "patch_listing_payload",
    "withdraw_listing_payload",
    "close_listing_payload",
    "create_buyer_payload",
    "patch_buyer_payload",
    "create_lockbox_payload",
    "request_showing_payload",
    "submit_offer_payload",
    "counter_offer_payload",
    "rebound_offer_payload",
    "create_contingency_payload",
    "clock_advance_payload",
]
