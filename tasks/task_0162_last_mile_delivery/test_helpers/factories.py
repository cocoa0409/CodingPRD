"""Payload factories — one per endpoint that accepts a body.

Each factory emits exactly the JSON-body schema PRD §3 narratives plus
PRD §4 endpoint table declare. Tests pass overrides for the values they
want to control. Only PRD-declared input fields are produced; computed
and system fields are omitted so the implementation cannot accidentally
accept them as input.

Timestamps are ISO 8601 UTC with three fractional digits per PRD §2.4.
"""
from __future__ import annotations

import math
import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .constants import (
    EARTH_RADIUS_KM,
    TEST_DEFAULTS,
)


# ---------------------------------------------------------------------------
# Time helpers — PRD §2.4 (timestamps) and §3.5 (UTC instants)
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


# Optional override: fixtures install a logical-clock provider so factory
# defaults follow the server's logical clock (PRD §2.11) instead of wall
# clock. Defaults to wall clock; fixtures.py sets _logical_now_provider
# to current_clock() once the tracker is initialized.
_logical_now_provider = None  # type: ignore


def set_logical_now_provider(provider) -> None:
    """Install a callable returning the current logical-clock UTC datetime.
    Used by factory defaults that need to anchor time windows / planned
    dates to the server's forward-only logical clock rather than wall
    clock. PRD §2.11."""
    global _logical_now_provider
    _logical_now_provider = provider


def logical_now() -> datetime:
    """Return the current logical-clock instant if a provider is
    installed, else wall-clock now."""
    if _logical_now_provider is not None:
        try:
            return _logical_now_provider()
        except Exception:
            pass
    return utcnow()


def iso_now() -> str:
    return iso_utc(utcnow())


def iso_at(year: int, month: int, day: int, hour: int = 0,
           minute: int = 0, second: int = 0,
           millis: int = 0) -> str:
    micros = millis * 1000
    return iso_utc(datetime(year, month, day, hour, minute, second,
                            micros, tzinfo=timezone.utc))


def parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 string, accepting both Z and +00:00 suffixes."""
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def add_hours(dt: datetime, hours: float) -> datetime:
    return dt + timedelta(hours=hours)


def add_minutes(dt: datetime, minutes: float) -> datetime:
    return dt + timedelta(minutes=minutes)


def add_days(dt: datetime, days: float) -> datetime:
    return dt + timedelta(days=days)


# ---------------------------------------------------------------------------
# Random helpers
# ---------------------------------------------------------------------------
def random_suffix(length: int = 8) -> str:
    return "".join(random.choices(string.ascii_uppercase + string.digits,
                                  k=length))


def random_email() -> str:
    return f"user_{random_suffix(8).lower()}@example.com"


def random_e164() -> str:
    return "+1555" + "".join(random.choices(string.digits, k=7))


def random_three_letter_code() -> str:
    return "".join(random.choices(string.ascii_uppercase, k=3))


def random_badge_id() -> str:
    return f"BADGE-{random_suffix(6)}"


# ---------------------------------------------------------------------------
# Haversine — PRD §3.7 (Earth radius 6371.0 km)
# ---------------------------------------------------------------------------
def haversine_km(lat1: float, lon1: float,
                 lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres using Earth radius 6371.0 km
    per PRD §3.7."""
    rlat1 = math.radians(lat1)
    rlat2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_KM * c


# ---------------------------------------------------------------------------
# Customer — PRD §3.1
# ---------------------------------------------------------------------------
def create_customer_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.1: 'contact email (unique, RFC 5322), full_name, phone
    (E.164), optional driver_release_authorized (default false)'."""
    defaults: Dict[str, Any] = {
        "email": random_email(),
        "full_name": f"Customer {random_suffix(4)}",
        "phone": random_e164(),
    }
    defaults.update(overrides)
    return defaults


def patch_customer_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.1: 'accepts full_name, phone, driver_release_authorized,
    default_address_id, and an optional version for concurrency'."""
    defaults: Dict[str, Any] = {}
    defaults.update(overrides)
    return defaults


def create_address_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.1: 'line1, city, postal_code, latitude, longitude,
    optional residential (default true)'."""
    defaults: Dict[str, Any] = {
        "line1": f"{random.randint(100, 9999)} Test St",
        "city": "Los Angeles",
        "postal_code": TEST_DEFAULTS["address_postal_code"],
        "latitude": TEST_DEFAULTS["address_lat"],
        "longitude": TEST_DEFAULTS["address_lon"],
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# TransitCenter — PRD §3.2
# ---------------------------------------------------------------------------
def create_transit_center_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.2: 'three-letter code, serviced_postal_prefixes array,
    optional hazmat_certified (default false)'."""
    defaults: Dict[str, Any] = {
        "code": random_three_letter_code(),
        "serviced_postal_prefixes": [
            TEST_DEFAULTS["transit_center_postal_prefix"],
        ],
        "latitude": TEST_DEFAULTS["transit_center_lat"],
        "longitude": TEST_DEFAULTS["transit_center_lon"],
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Driver — PRD §3.2
# ---------------------------------------------------------------------------
def create_driver_payload(home_center_id: str, **overrides) -> Dict[str, Any]:
    """PRD §3.2: 'badge_id (unique), home_center_id, optional
    hazmat_endorsement (default false)'."""
    defaults: Dict[str, Any] = {
        "badge_id": random_badge_id(),
        "home_center_id": home_center_id,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Parcel — PRD §3.3
# ---------------------------------------------------------------------------
def create_parcel_payload(customer_id: str, origin_center_id: str,
                          **overrides) -> Dict[str, Any]:
    """PRD §3.3: 'customer_id, optional destination_address_id (defaults
    to customer.default_address_id), origin_center_id, weight_kg,
    declared_value, optional signature_required (default false),
    optional hazmat_class (default NONE), time_window_start,
    time_window_end'.

    Defaults: time window covers tomorrow 08:00-20:00 UTC (relative to
    the LOGICAL clock per PRD §2.11) so the default planned_date (also
    tomorrow relative to logical clock) with depart hour 08:00 local
    starts strictly inside the parcel window — preventing
    ERR_TIME_WINDOW_INFEASIBLE in baseline fixtures.
    """
    now = logical_now()
    tomorrow = (now + timedelta(days=1)).date()
    window_start = datetime(
        tomorrow.year, tomorrow.month, tomorrow.day, 8, 0, 0,
        tzinfo=timezone.utc,
    )
    window_end = window_start + timedelta(hours=12)
    defaults: Dict[str, Any] = {
        "customer_id": customer_id,
        "origin_center_id": origin_center_id,
        "weight_kg": TEST_DEFAULTS["parcel_weight_kg"],
        "declared_value": TEST_DEFAULTS["parcel_declared_value"],
        "time_window_start": iso_utc(window_start),
        "time_window_end": iso_utc(window_end),
    }
    defaults.update(overrides)
    return defaults


def patch_parcel_payload(**overrides) -> Dict[str, Any]:
    """PRD §3.3 / §4: optional weight_kg, declared_value,
    signature_required, hazmat_class, destination_address_id,
    time_window_start, time_window_end, and an optional version."""
    defaults: Dict[str, Any] = {}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Route + RouteStop — PRD §3.4
# ---------------------------------------------------------------------------
def create_route_payload(center_id: str, driver_id: str,
                         planned_date: Optional[str] = None,
                         **overrides) -> Dict[str, Any]:
    """PRD §3.4: 'center_id, driver_id, planned_date (YYYY-MM-DD in the
    center's local time zone)'."""
    if planned_date is None:
        # Pick a date 1 day out so today's logical clock is before
        # depart-hour 08:00 local of that date. Uses LOGICAL clock
        # (PRD §2.11) so route windows align with parcel windows.
        planned_date = (logical_now() + timedelta(days=1)).date().isoformat()
    defaults: Dict[str, Any] = {
        "center_id": center_id,
        "driver_id": driver_id,
        "planned_date": planned_date,
    }
    defaults.update(overrides)
    return defaults


def create_stop_payload(parcel_id: str, **overrides) -> Dict[str, Any]:
    """PRD §3.4: 'supplies only the parcel_id of the parcel to be loaded'."""
    defaults: Dict[str, Any] = {"parcel_id": parcel_id}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# DeliveryAttempt — PRD §3.5
# ---------------------------------------------------------------------------
def create_attempt_payload(route_stop_id: str, outcome: str,
                           signature_blob_ref: Optional[str] = None,
                           release_location: Optional[str] = None,
                           **overrides) -> Dict[str, Any]:
    """PRD §3.5: 'route_stop_id and outcome ... depending on outcome,
    either signature_blob_ref (when outcome=DELIVERED_SIGNED) or
    release_location (when outcome=DRIVER_RELEASED)'."""
    payload: Dict[str, Any] = {
        "route_stop_id": route_stop_id,
        "outcome": outcome,
    }
    if signature_blob_ref is not None:
        payload["signature_blob_ref"] = signature_blob_ref
    if release_location is not None:
        payload["release_location"] = release_location
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Appointment — PRD §3.5
# ---------------------------------------------------------------------------
def create_appointment_payload(parcel_id: str,
                               requested_window_start: str,
                               requested_window_end: str,
                               **overrides) -> Dict[str, Any]:
    """PRD §3.5: 'target parcel_id, requested_window_start,
    requested_window_end'."""
    defaults: Dict[str, Any] = {
        "parcel_id": parcel_id,
        "requested_window_start": requested_window_start,
        "requested_window_end": requested_window_end,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Clock — PRD §2.11
# ---------------------------------------------------------------------------
def clock_advance_payload(to_iso8601: str) -> Dict[str, Any]:
    """PRD §2.11: 'request body as to_iso8601'."""
    return {"to_iso8601": to_iso8601}


# ---------------------------------------------------------------------------
# Optimistic concurrency — PRD §2.10
# ---------------------------------------------------------------------------
def with_version(payload: Dict[str, Any], version: int) -> Dict[str, Any]:
    """Attach an optional version for OCC per PRD §2.10."""
    out = dict(payload)
    out["version"] = version
    return out


__all__ = [
    "iso_utc",
    "utcnow",
    "iso_now",
    "iso_at",
    "parse_iso",
    "add_hours",
    "add_minutes",
    "add_days",
    "random_suffix",
    "random_email",
    "random_e164",
    "random_three_letter_code",
    "random_badge_id",
    "haversine_km",
    "create_customer_payload",
    "patch_customer_payload",
    "create_address_payload",
    "create_transit_center_payload",
    "create_driver_payload",
    "create_parcel_payload",
    "patch_parcel_payload",
    "create_route_payload",
    "create_stop_payload",
    "create_attempt_payload",
    "create_appointment_payload",
    "clock_advance_payload",
    "with_version",
]
