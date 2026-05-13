"""Payload factories — one per endpoint that takes a body.

Each factory emits input fields only (PRD-exact names) and accepts
**overrides so tests can pin the precise value under assertion.
"""
from __future__ import annotations
import uuid
import string
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


# ===========================================================================
# Uniqueness helpers
# ===========================================================================
def unique_suffix(length: int = 8) -> str:
    """Lowercase hex suffix that keeps payloads collision-free across tests."""
    return uuid.uuid4().hex[:length]


def unique_route_code(prefix: str = "RT") -> str:
    """Per PRD §3.2: uppercase, 3..12 chars, letters/digits/hyphen.

    Generates a hyphen-joined PREFIX-XXXXXX form that fits the 3..12 char limit.
    """
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits,
                                    k=4))
    return f"{prefix}-{suffix}"  # e.g. "RT-A1B2"


def unique_stop_code(prefix: str = "STP") -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits,
                                    k=4))
    return f"{prefix}-{suffix}"


def unique_plate_number(prefix: str = "PLT") -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits,
                                    k=5))
    return f"{prefix}{suffix}"


def unique_employee_code(prefix: str = "EMP") -> str:
    suffix = "".join(random.choices(string.digits, k=6))
    return f"{prefix}{suffix}"


def unique_department_code(prefix: str = "DEPT") -> str:
    suffix = "".join(random.choices(string.ascii_uppercase, k=3))
    return f"{prefix}-{suffix}"


# ===========================================================================
# Time helpers (PRD §2.4: ISO 8601 UTC with three fractional digits)
# ===========================================================================
def iso_z(dt: datetime) -> str:
    """ISO 8601 UTC with millisecond precision and Z suffix (PRD §2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def date_z(dt: datetime) -> str:
    """ISO 8601 UTC at midnight (date form): YYYY-MM-DDT00:00:00.000Z."""
    dt = dt.astimezone(timezone.utc)
    midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return iso_z(midnight)


def parse_iso(value: str) -> datetime:
    """Parse a PRD-format ISO 8601 timestamp (millisecond, Z suffix)."""
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def server_now() -> datetime:
    """Best-effort query of the platform clock.

    Tests advance the clock via POST /shuttle/_clock/advance (PRD §2.12);
    subsequent fixtures may need the new clock instant to compute future
    timestamps. We anchor against api_request_timestamp from a cheap GET
    on the audit-logs list; fall back to wall clock if anything goes wrong.
    """
    try:
        from .api_client import api_client
        from .test_users import TEST_USERS
        resp = api_client.list_audit_logs(
            TEST_USERS["dispatcher_headers"],
            params={"limit": 1, "offset": 0},
        )
        ts = resp.json().get("meta", {}).get("api_request_timestamp")
        if ts:
            return parse_iso(ts)
    except Exception:
        pass
    return datetime.now(timezone.utc)


# ===========================================================================
# Stops (PRD §3.1)
# ===========================================================================
def create_stop_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": unique_stop_code(),
        "name": f"Stop {unique_suffix(4)}",
        "latitude": 31.123456,
        "longitude": 121.123456,
        "has_shelter": False,
        "amenities": [],
        "capacity_reference": 50,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# Routes (PRD §3.2)
# ===========================================================================
def create_route_payload(start_stop_id: str, end_stop_id: str,
                         intermediate_stop_ids: Optional[List[str]] = None,
                         **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": unique_route_code(),
        "name": f"Route {unique_suffix(4)}",
        "start_stop_id": start_stop_id,
        "end_stop_id": end_stop_id,
        "intermediate_stop_ids": intermediate_stop_ids or [],
        "peak_frequency_minutes": 10,
        "offpeak_frequency_minutes": 30,
        "peak_windows": [["09:00", "11:00"]],
    }
    payload.update(overrides)
    return payload


def update_route_payload(**overrides: Any) -> Dict[str, Any]:
    """Empty by default; tests pass exactly the fields under modification."""
    return dict(overrides)


# ===========================================================================
# Vehicles (PRD §3.3)
# ===========================================================================
def create_vehicle_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "plate_number": unique_plate_number(),
        "seat_capacity": 20,
        "vehicle_type": "STANDARD",
    }
    payload.update(overrides)
    return payload


def start_maintenance_payload(window_start: str, window_end: str,
                              **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "maintenance_window_start": window_start,
        "maintenance_window_end": window_end,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# Drivers (PRD §3.3)
# ===========================================================================
def create_driver_payload(license_expiry_date: Optional[str] = None,
                          **overrides: Any) -> Dict[str, Any]:
    if license_expiry_date is None:
        license_expiry_date = iso_z(server_now() + timedelta(days=365))
    payload: Dict[str, Any] = {
        "employee_code": unique_employee_code("DRV"),
        "full_name": f"Driver {unique_suffix(4)}",
        "license_expiry_date": license_expiry_date,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# Run sheets (PRD §3.4)
# ===========================================================================
def create_run_sheet_payload(route_id: str, scheduled_departure: str,
                             assigned_driver_id: str,
                             scheduled_date: Optional[str] = None,
                             assigned_vehicle_id: Optional[str] = None,
                             **overrides: Any) -> Dict[str, Any]:
    if scheduled_date is None:
        scheduled_date = date_z(parse_iso(scheduled_departure))
    payload: Dict[str, Any] = {
        "route_id": route_id,
        "scheduled_date": scheduled_date,
        "scheduled_departure": scheduled_departure,
        "assigned_driver_id": assigned_driver_id,
    }
    if assigned_vehicle_id is not None:
        payload["assigned_vehicle_id"] = assigned_vehicle_id
    payload.update(overrides)
    return payload


# ===========================================================================
# Reservations (PRD §3.6)
# ===========================================================================
def create_reservation_payload(employee_id: str, boarding_stop_id: str,
                               alighting_stop_id: str,
                               payer_mode: str = "SELF_PAY",
                               department_code: Optional[str] = None,
                               **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "employee_id": employee_id,
        "boarding_stop_id": boarding_stop_id,
        "alighting_stop_id": alighting_stop_id,
        "payer_mode": payer_mode,
    }
    if department_code is not None:
        payload["department_code"] = department_code
    payload.update(overrides)
    return payload


# ===========================================================================
# Check-in (PRD §3.6)
# ===========================================================================
def check_in_payload(reservation_id: str, boarded_stop_id: str,
                     check_in_method: str = "QR",
                     **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "reservation_id": reservation_id,
        "check_in_method": check_in_method,
        "boarded_stop_id": boarded_stop_id,
    }
    payload.update(overrides)
    return payload


def update_ridership_payload(alighted_stop_id: str,
                             **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"alighted_stop_id": alighted_stop_id}
    payload.update(overrides)
    return payload


# ===========================================================================
# Delays (PRD §3.5)
# ===========================================================================
def report_delay_payload(cause: str, delay_minutes: int,
                         affected_from_stop_id: str,
                         **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "cause": cause,
        "delay_minutes": delay_minutes,
        "affected_from_stop_id": affected_from_stop_id,
    }
    payload.update(overrides)
    return payload


def dispatch_substitute_payload(vehicle_id: str,
                                **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"vehicle_id": vehicle_id}
    payload.update(overrides)
    return payload


# ===========================================================================
# Bills (PRD §3.8)
# ===========================================================================
def create_bill_payload(billing_month: str, payer_scope: str, payer_id: str,
                        **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "billing_month": billing_month,
        "payer_scope": payer_scope,
        "payer_id": payer_id,
    }
    payload.update(overrides)
    return payload


# ===========================================================================
# Clock (PRD §2.12)
# ===========================================================================
def clock_advance_payload(to_timestamp: str,
                          **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_timestamp": to_timestamp}
    payload.update(overrides)
    return payload


__all__ = [
    "unique_suffix",
    "unique_route_code",
    "unique_stop_code",
    "unique_plate_number",
    "unique_employee_code",
    "unique_department_code",
    "iso_z",
    "date_z",
    "parse_iso",
    "server_now",
    "create_stop_payload",
    "create_route_payload",
    "update_route_payload",
    "create_vehicle_payload",
    "start_maintenance_payload",
    "create_driver_payload",
    "create_run_sheet_payload",
    "create_reservation_payload",
    "check_in_payload",
    "update_ridership_payload",
    "report_delay_payload",
    "dispatch_substitute_payload",
    "create_bill_payload",
    "clock_advance_payload",
]
