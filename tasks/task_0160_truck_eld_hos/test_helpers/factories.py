"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the JSON-body schema the PRD declares for the
request body (PRD §3 narratives). Tests pass overrides for the values
they want to control. Only PRD-declared input fields are produced;
computed / system / append-only fields are intentionally omitted.

PRD §2.6: timestamps are ISO 8601 UTC with three fractional digits.
"""
from __future__ import annotations

import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Time helpers — PRD §2.6
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


def parse_iso(iso_ts: str) -> datetime:
    """Parse an ISO 8601 string accepting both 'Z' and '+00:00' offsets."""
    return datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))


def add_seconds(iso_ts: str, seconds: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(seconds=seconds))


def add_minutes(iso_ts: str, minutes: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(minutes=minutes))


def add_hours(iso_ts: str, hours: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(hours=hours))


def add_days(iso_ts: str, days: int) -> str:
    return iso_utc(parse_iso(iso_ts) + timedelta(days=days))


# ---------------------------------------------------------------------------
# Random helpers — cross-test uniqueness
# ---------------------------------------------------------------------------
def random_suffix(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def random_digits(n: int) -> str:
    return "".join(random.choices(string.digits, k=n))


_VIN_ALPHABET = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"  # exclude I, O, Q


def random_vin() -> str:
    """Generate a syntactically valid VIN per PRD §3.1:
    exactly 17 uppercase alphanumeric characters excluding I, O, and Q."""
    return "".join(random.choices(_VIN_ALPHABET, k=17))


_CDL_ALPHABET = string.ascii_uppercase + string.digits


def random_cdl() -> str:
    """PRD §3.1: cdl_number is six to twenty uppercase alphanumeric
    characters. We standardise on a length within range to keep tests
    deterministic."""
    return "".join(random.choices(_CDL_ALPHABET, k=12))


def random_dot_number() -> str:
    """PRD §3.1: USDOT number is digits only, five to eight characters
    long."""
    return random_digits(7)


def random_serial() -> str:
    """PRD §3.1: serial_number is six to thirty-two characters long."""
    return "ELD" + random_suffix(12).upper()


# ---------------------------------------------------------------------------
# Carrier — POST /carriers
# ---------------------------------------------------------------------------
def create_carrier_payload(
    *,
    dot_number: Optional[str] = None,
    legal_name: Optional[str] = None,
    safety_contact_user_id: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "dot_number": dot_number or random_dot_number(),
        "legal_name": legal_name or TEST_DEFAULTS["CARRIER_LEGAL_NAME"],
        "safety_contact_user_id": (
            safety_contact_user_id or f"safety-{random_suffix()}"
        ),
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# ELD device — POST /eld-devices
# ---------------------------------------------------------------------------
def create_eld_device_payload(
    *,
    serial_number: Optional[str] = None,
    firmware_version: Optional[str] = None,
    certified_for_fmcsa: Optional[bool] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "serial_number": serial_number or random_serial(),
        "firmware_version": (
            firmware_version or TEST_DEFAULTS["DEFAULT_FIRMWARE"]
        ),
    }
    if certified_for_fmcsa is not None:
        payload["certified_for_fmcsa"] = certified_for_fmcsa
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Vehicle — POST /vehicles
# ---------------------------------------------------------------------------
def create_vehicle_payload(
    *,
    vin: Optional[str] = None,
    carrier_id: str,
    eld_device_id: str,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "vin": vin or random_vin(),
        "carrier_id": carrier_id,
        "eld_device_id": eld_device_id,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Driver — POST /drivers
# ---------------------------------------------------------------------------
def create_driver_payload(
    *,
    cdl_number: Optional[str] = None,
    full_name: Optional[str] = None,
    carrier_id: str,
    cycle_type: Optional[str] = None,
    home_terminal_timezone: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "cdl_number": cdl_number or random_cdl(),
        "full_name": full_name or TEST_DEFAULTS["DRIVER_FULL_NAME"],
        "carrier_id": carrier_id,
    }
    if cycle_type is not None:
        payload["cycle_type"] = cycle_type
    if home_terminal_timezone is not None:
        payload["home_terminal_timezone"] = home_terminal_timezone
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Bind — POST /drivers/{id}/bind
# ---------------------------------------------------------------------------
def bind_payload(*, vehicle_id: str, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"vehicle_id": vehicle_id}
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# DutyEvent — POST /drivers/{id}/duty-events
# ---------------------------------------------------------------------------
def create_duty_event_payload(
    *,
    new_status: str,
    event_time: str,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    vehicle_id: Optional[str] = None,
    odometer_miles: Optional[float] = None,
    annotation: Optional[str] = None,
    adverse_conditions_exemption_id: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "new_status": new_status,
        "event_time": event_time,
        "latitude": (
            TEST_DEFAULTS["DEFAULT_LAT"] if latitude is None else latitude
        ),
        "longitude": (
            TEST_DEFAULTS["DEFAULT_LON"] if longitude is None else longitude
        ),
    }
    if vehicle_id is not None:
        payload["vehicle_id"] = vehicle_id
    if odometer_miles is not None:
        payload["odometer_miles"] = odometer_miles
    if annotation is not None:
        payload["annotation"] = annotation
    if adverse_conditions_exemption_id is not None:
        payload["adverse_conditions_exemption_id"] = (
            adverse_conditions_exemption_id
        )
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# DutyEvent edit — POST /drivers/{id}/duty-events/{event_id}/edit
# ---------------------------------------------------------------------------
def edit_duty_event_payload(
    *,
    new_status: Optional[str] = None,
    event_time: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    odometer_miles: Optional[float] = None,
    annotation: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if new_status is not None:
        payload["new_status"] = new_status
    if event_time is not None:
        payload["event_time"] = event_time
    if latitude is not None:
        payload["latitude"] = latitude
    if longitude is not None:
        payload["longitude"] = longitude
    if odometer_miles is not None:
        payload["odometer_miles"] = odometer_miles
    if annotation is not None:
        payload["annotation"] = annotation
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Adverse conditions — POST /drivers/{id}/adverse-conditions
# ---------------------------------------------------------------------------
def create_adverse_conditions_payload(
    *,
    declared_at: str,
    reason: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "declared_at": declared_at,
        "reason": reason or TEST_DEFAULTS["DEFAULT_REASON"],
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Clock advance — POST /_clock/advance
# ---------------------------------------------------------------------------
def clock_advance_payload(*, to: str, **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to": to}
    payload.update(extra)
    return payload


__all__ = [
    "iso_utc", "utcnow", "iso_now", "parse_iso",
    "add_seconds", "add_minutes", "add_hours", "add_days",
    "random_suffix", "random_digits",
    "random_vin", "random_cdl", "random_dot_number", "random_serial",
    "create_carrier_payload",
    "create_eld_device_payload",
    "create_vehicle_payload",
    "create_driver_payload",
    "bind_payload",
    "create_duty_event_payload",
    "edit_duty_event_payload",
    "create_adverse_conditions_payload",
    "clock_advance_payload",
]
