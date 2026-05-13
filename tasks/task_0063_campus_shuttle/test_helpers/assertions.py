"""Per-entity assertion helpers for Campus Shuttle Dispatch responses.

Validates shape against PRD §2.4 (common-fields rules), §3.x (per-entity
fields). Append-only entities (RouteVersion, RidershipRecord, DelayEvent,
AuditLog) MUST NOT carry updated_at/version — see PRD §2.4.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ===========================================================================
# Allowed enum values (PRD §3)
# ===========================================================================
ROUTE_STATES = {"DRAFT", "ACTIVE", "RETIRED"}
STOP_STATES = {"DRAFT", "ACTIVE", "OFFSHELF"}
VEHICLE_STATES = {"ACTIVE", "MAINTENANCE", "RETIRED"}
VEHICLE_TYPES = {"STANDARD", "ELECTRIC", "SHUTTLE_VAN"}
DRIVER_STATES = {"ACTIVE", "SUSPENDED", "OFFBOARDED"}
RUN_SHEET_STATES = {
    "PLANNED", "BOARDING", "IN_TRANSIT",
    "DELAYED", "COMPLETED", "CANCELLED",
}
RESERVATION_STATES = {
    "CONFIRMED", "WAITLISTED", "CHECKED_IN",
    "COMPLETED", "CANCELLED", "NO_SHOW",
}
PAYER_MODES = {"SELF_PAY", "DEPARTMENT_PAID"}
PAYER_SCOPES = {"EMPLOYEE", "DEPARTMENT"}
BILL_STATES = {"DRAFT", "FINALIZED", "SETTLED", "REFUNDED"}
CHECK_IN_METHODS = {"QR", "CARD", "FACE"}
DELAY_CAUSES = {"TRAFFIC", "BREAKDOWN", "WEATHER"}
AMENITIES = {"LIGHTING", "SEATING", "USB", "DISPLAY", "RAMP"}
AUDIT_EVENT_TYPES = {
    "RESERVATION_CREATED", "RESERVATION_CANCELLED",
    "RESERVATION_CHECKED_IN", "RESERVATION_NO_SHOW",
    "DELAY_REPORTED", "SUBSTITUTE_DISPATCHED",
    "ROUTE_PUBLISHED", "BILL_REFUNDED",
}
AUDIT_SUBJECT_TYPES = {
    "Reservation", "RunSheet", "Route", "MonthlyBill", "DelayEvent",
}


# ===========================================================================
# Common-fields helpers (PRD §2.4)
# ===========================================================================
def _assert_versioned_common(data: Dict[str, Any], label: str) -> None:
    """PRD §2.4 versioned envelope: id + created_at + updated_at + version."""
    assert is_valid_uuid(data.get("id", "")), \
        f"{label}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{label}.updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    v = data.get("version")
    assert isinstance(v, int) and v >= 1, \
        f"{label}.version must be a non-negative integer starting at 1, got {v!r}"


def _assert_append_only_common(data: Dict[str, Any], label: str) -> None:
    """PRD §2.4: append-only entities carry only id + created_at."""
    assert is_valid_uuid(data.get("id", "")), \
        f"{label}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}"


# ===========================================================================
# Stop
# ===========================================================================
def assert_stop(data: Dict[str, Any]) -> None:
    _assert_versioned_common(data, "Stop")
    assert isinstance(data.get("code"), str) and data["code"]
    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data["latitude"], (int, float))
    assert -90 <= data["latitude"] <= 90
    assert isinstance(data["longitude"], (int, float))
    assert -180 <= data["longitude"] <= 180
    assert isinstance(data.get("has_shelter"), bool)
    amenities = data.get("amenities", [])
    assert isinstance(amenities, list)
    for tag in amenities:
        assert tag in AMENITIES, f"Stop.amenities item {tag!r} not in {AMENITIES}"
    assert isinstance(data["capacity_reference"], int)
    assert 1 <= data["capacity_reference"] <= 500
    assert data["status"] in STOP_STATES, \
        f"Stop.status {data['status']!r} not in {STOP_STATES}"


# ===========================================================================
# Route
# ===========================================================================
def assert_route(data: Dict[str, Any]) -> None:
    _assert_versioned_common(data, "Route")
    assert isinstance(data.get("code"), str) and data["code"]
    assert isinstance(data.get("name"), str)
    assert isinstance(data.get("start_stop_id"), str)
    assert isinstance(data.get("end_stop_id"), str)
    assert isinstance(data.get("intermediate_stop_ids"), list)
    for sid in data["intermediate_stop_ids"]:
        assert isinstance(sid, str)
    assert data["status"] in ROUTE_STATES, \
        f"Route.status {data['status']!r} not in {ROUTE_STATES}"
    assert isinstance(data["version_number"], int) and data["version_number"] >= 1
    assert isinstance(data["peak_frequency_minutes"], int)
    assert 5 <= data["peak_frequency_minutes"] <= 60
    assert isinstance(data["offpeak_frequency_minutes"], int)
    assert 5 <= data["offpeak_frequency_minutes"] <= 120
    assert data["peak_frequency_minutes"] <= data["offpeak_frequency_minutes"]
    pw = data.get("peak_windows", [])
    assert isinstance(pw, list)
    for window in pw:
        assert isinstance(window, list) and len(window) == 2
        assert all(isinstance(part, str) for part in window)


def assert_route_published_fields(data: Dict[str, Any]) -> None:
    """Post-publish fields: distance / duration estimates must be set."""
    assert isinstance(data["estimated_distance_km"], (int, float))
    assert data["estimated_distance_km"] >= 0
    assert isinstance(data["estimated_duration_minutes"], int)
    assert data["estimated_duration_minutes"] >= 0


# ===========================================================================
# RouteVersion (append-only)
# ===========================================================================
def assert_route_version(data: Dict[str, Any]) -> None:
    _assert_append_only_common(data, "RouteVersion")
    assert isinstance(data.get("route_code"), str) and data["route_code"]
    assert isinstance(data["version_number"], int) and data["version_number"] >= 1
    seq = data.get("stop_sequence_snapshot")
    assert isinstance(seq, list) and len(seq) >= 2
    assert isinstance(data["peak_frequency_minutes"], int)
    assert isinstance(data["offpeak_frequency_minutes"], int)
    pw = data.get("peak_windows", [])
    assert isinstance(pw, list)
    assert is_iso8601_timestamp(data.get("published_at", "")), \
        f"RouteVersion.published_at must be ISO 8601, got {data.get('published_at')!r}"
    if data.get("retired_at") is not None:
        assert is_iso8601_timestamp(data["retired_at"])


# ===========================================================================
# Vehicle
# ===========================================================================
def assert_vehicle(data: Dict[str, Any]) -> None:
    _assert_versioned_common(data, "Vehicle")
    assert isinstance(data.get("plate_number"), str) and data["plate_number"]
    assert isinstance(data["seat_capacity"], int)
    assert 8 <= data["seat_capacity"] <= 80
    assert data["vehicle_type"] in VEHICLE_TYPES
    assert data["status"] in VEHICLE_STATES
    # Maintenance window fields populated only while MAINTENANCE
    if data["status"] == "MAINTENANCE":
        assert is_iso8601_timestamp(data.get("maintenance_window_start", "")), \
            "Vehicle.maintenance_window_start must be ISO 8601 while in MAINTENANCE"
        assert is_iso8601_timestamp(data.get("maintenance_window_end", "")), \
            "Vehicle.maintenance_window_end must be ISO 8601 while in MAINTENANCE"


# ===========================================================================
# Driver
# ===========================================================================
def assert_driver(data: Dict[str, Any]) -> None:
    _assert_versioned_common(data, "Driver")
    assert isinstance(data.get("employee_code"), str) and data["employee_code"]
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert is_iso8601_timestamp(data.get("license_expiry_date", "")), \
        f"Driver.license_expiry_date must be ISO 8601, got {data.get('license_expiry_date')!r}"
    assert data["status"] in DRIVER_STATES


# ===========================================================================
# RunSheet
# ===========================================================================
def assert_run_sheet(data: Dict[str, Any]) -> None:
    _assert_versioned_common(data, "RunSheet")
    assert isinstance(data.get("route_id"), str)
    assert isinstance(data["route_version_number"], int)
    assert is_iso8601_timestamp(data.get("scheduled_date", ""))
    assert is_iso8601_timestamp(data.get("scheduled_departure", ""))
    assert is_iso8601_timestamp(data.get("scheduled_arrival", ""))
    assert isinstance(data.get("assigned_driver_id"), str)
    assert data["status"] in RUN_SHEET_STATES
    assert isinstance(data["capacity_remaining"], int) and data["capacity_remaining"] >= 0
    assert isinstance(data["delay_minutes_accumulated"], int)
    assert data["delay_minutes_accumulated"] >= 0


# ===========================================================================
# Reservation
# ===========================================================================
def assert_reservation(data: Dict[str, Any]) -> None:
    _assert_versioned_common(data, "Reservation")
    assert isinstance(data.get("employee_id"), str) and data["employee_id"]
    assert isinstance(data.get("run_sheet_id"), str)
    assert isinstance(data.get("boarding_stop_id"), str)
    assert isinstance(data.get("alighting_stop_id"), str)
    assert data["status"] in RESERVATION_STATES
    assert data["payer_mode"] in PAYER_MODES
    if data["payer_mode"] == "DEPARTMENT_PAID":
        assert data.get("department_code"), \
            "Reservation.department_code is required when payer_mode==DEPARTMENT_PAID"
    elif data["payer_mode"] == "SELF_PAY":
        assert not data.get("department_code"), \
            "Reservation.department_code must be empty when payer_mode==SELF_PAY"
    assert isinstance(data["fare_cents"], int) and data["fare_cents"] >= 0
    pts = data.get("no_show_penalty_points", 0)
    assert isinstance(pts, int) and pts >= 0
    if data["status"] == "WAITLISTED":
        assert isinstance(data.get("waitlist_position"), int)
        assert data["waitlist_position"] >= 1
    else:
        assert data.get("waitlist_position") in (None, 0) or data.get("waitlist_position") is None
    if data["status"] == "CANCELLED":
        assert is_iso8601_timestamp(data.get("cancelled_at", ""))


# ===========================================================================
# RidershipRecord (append-only)
# ===========================================================================
def assert_ridership_record(data: Dict[str, Any]) -> None:
    _assert_append_only_common(data, "RidershipRecord")
    assert isinstance(data.get("run_sheet_id"), str)
    assert isinstance(data.get("employee_id"), str)
    assert data["check_in_method"] in CHECK_IN_METHODS
    assert isinstance(data.get("boarded_stop_id"), str)
    assert is_iso8601_timestamp(data.get("boarded_at", ""))
    if data.get("alighted_at") is not None:
        assert is_iso8601_timestamp(data["alighted_at"])


# ===========================================================================
# DelayEvent (append-only)
# ===========================================================================
def assert_delay_event(data: Dict[str, Any]) -> None:
    _assert_append_only_common(data, "DelayEvent")
    assert isinstance(data.get("run_sheet_id"), str)
    assert data["cause"] in DELAY_CAUSES
    assert isinstance(data["delay_minutes"], int)
    assert 1 <= data["delay_minutes"] <= 480
    assert isinstance(data.get("affected_from_stop_id"), str)
    assert isinstance(data["notification_dispatched"], bool)
    assert isinstance(data["substitute_dispatched"], bool)
    assert is_iso8601_timestamp(data.get("reported_at", ""))


# ===========================================================================
# MonthlyBill
# ===========================================================================
def assert_monthly_bill(data: Dict[str, Any]) -> None:
    _assert_versioned_common(data, "MonthlyBill")
    assert isinstance(data.get("billing_month"), str)
    assert data["payer_scope"] in PAYER_SCOPES
    assert isinstance(data.get("payer_id"), str) and data["payer_id"]
    assert data["status"] in BILL_STATES
    assert isinstance(data.get("refund_cents", 0), int)
    if data["status"] in {"FINALIZED", "REFUNDED", "SETTLED"}:
        assert isinstance(data.get("gross_cents"), int)
        assert data["gross_cents"] >= 0
        assert isinstance(data.get("line_count"), int)
        assert data["line_count"] >= 0
        assert is_iso8601_timestamp(data.get("finalized_at", ""))
    if data["status"] == "SETTLED":
        assert isinstance(data.get("net_cents"), int)
        # PRD §3.8: net_cents = gross_cents - refund_cents
        assert data["net_cents"] == data["gross_cents"] - data["refund_cents"], \
            f"MonthlyBill.net_cents ({data['net_cents']}) must equal gross_cents - refund_cents"


# ===========================================================================
# AuditLog (append-only)
# ===========================================================================
def assert_audit_log(data: Dict[str, Any]) -> None:
    _assert_append_only_common(data, "AuditLog")
    assert data["event_type"] in AUDIT_EVENT_TYPES
    assert data["subject_type"] in AUDIT_SUBJECT_TYPES
    assert isinstance(data.get("subject_id"), str)
    assert isinstance(data.get("actor_role"), str)
    assert isinstance(data.get("actor_id"), str)
    assert isinstance(data.get("payload"), dict)


def find_audit_entries(entries: Iterable[Dict[str, Any]],
                       *, event_type: Optional[str] = None,
                       subject_type: Optional[str] = None,
                       subject_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Filter helper used by side-effect tests."""
    out: List[Dict[str, Any]] = []
    for entry in entries:
        if event_type and entry.get("event_type") != event_type:
            continue
        if subject_type and entry.get("subject_type") != subject_type:
            continue
        if subject_id and entry.get("subject_id") != subject_id:
            continue
        out.append(entry)
    return out


__all__ = [
    "ROUTE_STATES", "STOP_STATES", "VEHICLE_STATES", "VEHICLE_TYPES",
    "DRIVER_STATES", "RUN_SHEET_STATES", "RESERVATION_STATES",
    "PAYER_MODES", "PAYER_SCOPES", "BILL_STATES", "CHECK_IN_METHODS",
    "DELAY_CAUSES", "AMENITIES",
    "AUDIT_EVENT_TYPES", "AUDIT_SUBJECT_TYPES",
    "assert_stop", "assert_route", "assert_route_published_fields",
    "assert_route_version", "assert_vehicle", "assert_driver",
    "assert_run_sheet", "assert_reservation", "assert_ridership_record",
    "assert_delay_event", "assert_monthly_bill", "assert_audit_log",
    "find_audit_entries",
]
