"""Payload factories — one per entity, input fields only per PRD §3.

Every factory accepts **overrides so tests can pin the exact inputs they
care about (e.g., balance, axle_count, base_rate_cents) without
restating defaults.
"""
from __future__ import annotations

import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Random / utility helpers
# ---------------------------------------------------------------------------
def random_suffix(n: int = 6) -> str:
    """Random uppercase alnum suffix for uniqueness in plate/serial."""
    return "".join(
        random.choices(string.ascii_uppercase + string.digits, k=n)
    )


def random_serial() -> str:
    """A unique 16-char serial in [A-Z0-9]; falls within 10..24 length."""
    return "SN" + uuid.uuid4().hex.upper()[:14]


def random_plate() -> str:
    """A unique plate number 1..10 chars from [A-Z0-9-]."""
    return "P" + random_suffix(7)


def random_holder_name(prefix: str = "Holder") -> str:
    return f"{prefix} {random_suffix(4)}"


# ---------------------------------------------------------------------------
# ISO-8601 helpers — PRD §2.4 requires three fractional digits
# ---------------------------------------------------------------------------
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime) -> str:
    """Format with milliseconds and trailing Z, matching PRD §2.4 shape."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def iso_now() -> str:
    return iso_utc(utcnow())


def add_days(dt: datetime, days: int) -> datetime:
    return dt + timedelta(days=days)


def add_seconds(dt: datetime, seconds: float) -> datetime:
    return dt + timedelta(seconds=seconds)


def parse_iso(s: str) -> datetime:
    """Parse an ISO-8601 UTC timestamp (with optional fractional digits and
    'Z' suffix) back to a tz-aware datetime."""
    s = s.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


# ---------------------------------------------------------------------------
# Account — PRD §3.1
# ---------------------------------------------------------------------------
def create_account_payload(**overrides: Any) -> Dict[str, Any]:
    """Default-input payload for POST /accounts.

    PRD §3.1 requires holder_name and home_agency_code; auto-reload knobs
    and payment_method_token are optional. payment_method_token is
    'required if auto_reload_enabled is true'.
    """
    defaults: Dict[str, Any] = {
        "holder_name": random_holder_name(),
        "home_agency_code": TEST_DEFAULTS["HOME_AGENCY_CODE"],
    }
    defaults.update(overrides)
    return defaults


def patch_account_payload(**overrides: Any) -> Dict[str, Any]:
    """Default-input payload for PATCH /accounts/{id}.

    PRD §2.7: version is optional; when present the OCC check fires.
    """
    return dict(overrides)


# ---------------------------------------------------------------------------
# Vehicle — PRD §3.2
# ---------------------------------------------------------------------------
def create_vehicle_payload(**overrides: Any) -> Dict[str, Any]:
    """Default-input payload for POST /accounts/{id}/vehicles."""
    defaults: Dict[str, Any] = {
        "plate_number": random_plate(),
        "plate_state": TEST_DEFAULTS["PLATE_STATE_DEFAULT"],
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Transponder — PRD §3.2
# ---------------------------------------------------------------------------
def create_transponder_payload(**overrides: Any) -> Dict[str, Any]:
    """Default-input payload for POST /accounts/{id}/transponders."""
    defaults: Dict[str, Any] = {
        "serial_number": random_serial(),
    }
    defaults.update(overrides)
    return defaults


def bind_transponder_payload(vehicle_id: str,
                             **overrides: Any) -> Dict[str, Any]:
    """Default-input payload for the bind endpoint."""
    defaults: Dict[str, Any] = {"vehicle_id": vehicle_id}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Reload — PRD §3.4
# ---------------------------------------------------------------------------
def create_reload_payload(amount_cents: int = 5000,
                          **overrides: Any) -> Dict[str, Any]:
    """Default-input payload for POST /accounts/{id}/reloads."""
    defaults: Dict[str, Any] = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Toll event ingest — PRD §3.3
# ---------------------------------------------------------------------------
def create_toll_event_payload(gantry_id: Optional[str] = None,
                              agency_code: str = "NY_EZPASS",
                              base_rate_cents: int = 200,
                              read_at: Optional[str] = None,
                              **overrides: Any) -> Dict[str, Any]:
    """Default-input payload for POST /toll-events.

    PRD §3.3 lists gantry_id, agency_code, base_rate_cents, and read_at
    as required; the rest (transponder_serial, plate_number, plate_state,
    declared_occupants, hov_lane) are optional with documented defaults.
    """
    defaults: Dict[str, Any] = {
        "gantry_id": gantry_id or TEST_DEFAULTS["GANTRY_ID"],
        "agency_code": agency_code,
        "base_rate_cents": base_rate_cents,
        "read_at": read_at or iso_now(),
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Fine actions — PRD §3.6
# ---------------------------------------------------------------------------
def pay_fine_payload(payment_method_token: Optional[str] = None,
                     **overrides: Any) -> Dict[str, Any]:
    """Default-input payload for POST /fines/{id}/pay.

    PRD §3.6: "An AccountHolder who acknowledges a fine pays it by
    referencing the fine and supplying a `payment_method_token`."
    """
    defaults: Dict[str, Any] = {
        "payment_method_token": (
            payment_method_token or TEST_DEFAULTS["PAYMENT_METHOD_TOKEN"]
        ),
    }
    defaults.update(overrides)
    return defaults


def dispute_fine_payload(reason: str = "I dispute this",
                         **overrides: Any) -> Dict[str, Any]:
    """Default-input payload for POST /fines/{id}/dispute.

    PRD §3.6: "the account holder may instead contest a `PENDING` fine
    by opening a dispute with an explanatory `reason` string."
    """
    defaults: Dict[str, Any] = {"reason": reason}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Interop policy — PRD §3.7
# ---------------------------------------------------------------------------
def create_interop_policy_payload(home_agency: str,
                                  gantry_agency: str,
                                  surcharge_bps: int = 0,
                                  discount_bps: int = 0,
                                  **overrides: Any) -> Dict[str, Any]:
    """Default-input payload for POST /interop-policies."""
    defaults: Dict[str, Any] = {
        "home_agency": home_agency,
        "gantry_agency": gantry_agency,
        "surcharge_bps": surcharge_bps,
        "discount_bps": discount_bps,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Clock — PRD §3.7
# ---------------------------------------------------------------------------
def clock_advance_payload(to_iso8601: str,
                          **overrides: Any) -> Dict[str, Any]:
    """Default-input payload for POST /_clock/advance."""
    defaults: Dict[str, Any] = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults


__all__ = [
    "random_suffix",
    "random_serial",
    "random_plate",
    "random_holder_name",
    "utcnow",
    "iso_utc",
    "iso_now",
    "add_days",
    "add_seconds",
    "parse_iso",
    "create_account_payload",
    "patch_account_payload",
    "create_vehicle_payload",
    "create_transponder_payload",
    "bind_transponder_payload",
    "create_reload_payload",
    "create_toll_event_payload",
    "pay_fine_payload",
    "dispute_fine_payload",
    "create_interop_policy_payload",
    "clock_advance_payload",
]
