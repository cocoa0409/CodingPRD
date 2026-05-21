"""Per-entity response-shape assertions and domain invariant checkers.

Each assert_<entity>(data) validates the response payload's shape
against the contract declared in PRD §2.4 (common fields) plus the
entity-specific fields stated in §3.1–§3.5 narratives. The lightweight
entities (Address, RouteStop, DeliveryAttempt) carry only id and
created_at per PRD §2.4 and intentionally do NOT carry updated_at or
version — assertions reflect that.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Shape helpers
# ---------------------------------------------------------------------------
def assert_common_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: 'All top-level resources ... share id, created_at,
    updated_at, version'."""
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be a positive integer, got {data.get('version')!r}"


def assert_lean_fields(data: Dict[str, Any]) -> None:
    """PRD §2.4: 'Two scaffold entities are intentionally lightweight
    and carry only the id and created_at fields'. Used for Address,
    RouteStop, DeliveryAttempt."""
    assert is_valid_uuid(data.get("id", "")), \
        f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"


# ---------------------------------------------------------------------------
# Customer — PRD §3.1
# ---------------------------------------------------------------------------
def assert_customer(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("email"), str) and "@" in data["email"]
    assert isinstance(data.get("full_name"), str) \
        and len(data["full_name"]) > 0
    assert isinstance(data.get("phone"), str) \
        and data["phone"].startswith("+")
    # default_address_id is nullable per PRD §3.1.
    if data.get("default_address_id") is not None:
        assert is_valid_uuid(data["default_address_id"])
    assert isinstance(data.get("driver_release_authorized"), bool)
    # PRD §3.1 / §3.7: rolling 30d counter is an integer.
    assert isinstance(data.get("redelivery_attempts_used_30d"), int) \
        and data["redelivery_attempts_used_30d"] >= 0


# ---------------------------------------------------------------------------
# Address — PRD §3.1
# ---------------------------------------------------------------------------
def assert_address(data: Dict[str, Any]) -> None:
    assert_lean_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data.get("line1"), str) and len(data["line1"]) > 0
    assert isinstance(data.get("city"), str) and len(data["city"]) > 0
    assert isinstance(data.get("postal_code"), str)
    # PRD §3.1: 'a five-digit postal_code'.
    assert re.match(r"^\d{5}$", data["postal_code"]) is not None
    assert isinstance(data.get("latitude"), (int, float))
    assert isinstance(data.get("longitude"), (int, float))
    assert -90.0 <= data["latitude"] <= 90.0
    assert -180.0 <= data["longitude"] <= 180.0
    assert isinstance(data.get("residential"), bool)
    # PRD §2.4 explicitly says Address omits updated_at and version.
    assert "updated_at" not in data, \
        "Address must NOT carry updated_at (PRD §2.4 — lean entity)"
    assert "version" not in data, \
        "Address must NOT carry version (PRD §2.4 — lean entity)"


# ---------------------------------------------------------------------------
# TransitCenter — PRD §3.2
# ---------------------------------------------------------------------------
def assert_transit_center(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    code = data.get("code", "")
    assert isinstance(code, str) and len(code) == 3 and code.isupper() \
        and code.isalpha(), \
        f"code must be exactly 3 uppercase letters, got {code!r}"
    prefixes = data.get("serviced_postal_prefixes")
    assert isinstance(prefixes, list)
    for p in prefixes:
        assert isinstance(p, str) \
            and re.match(r"^\d{3}$", p) is not None, \
            f"serviced_postal_prefix must be a 3-digit string, got {p!r}"
    assert isinstance(data.get("hazmat_certified"), bool)
    assert isinstance(data.get("parcels_on_belt"), int) \
        and data["parcels_on_belt"] >= 0


# ---------------------------------------------------------------------------
# Driver — PRD §3.2
# ---------------------------------------------------------------------------
DRIVER_STATUSES = {"OFF_DUTY", "ON_DUTY", "ON_ROUTE", "RETURNED"}


def assert_driver(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data.get("badge_id"), str) \
        and len(data["badge_id"]) > 0
    assert is_valid_uuid(data.get("home_center_id", ""))
    assert isinstance(data.get("hazmat_endorsement"), bool)
    assert data.get("status") in DRIVER_STATUSES, \
        f"Driver.status must be one of {DRIVER_STATUSES}, " \
        f"got {data.get('status')!r}"


# ---------------------------------------------------------------------------
# Parcel — PRD §3.3, §3.5
# ---------------------------------------------------------------------------
PARCEL_STATUSES = {
    "INDUCTED", "IN_TRANSIT_HUB", "SORTED", "ON_VEHICLE",
    "OUT_FOR_DELIVERY", "DELIVERED", "EXCEPTION", "RETURNED_TO_SENDER",
}
HAZMAT_CLASSES = {
    "NONE", "CLASS_2", "CLASS_3", "CLASS_4", "CLASS_8", "CLASS_9",
}
LAST_ATTEMPT_OUTCOMES = {
    "NONE", "DELIVERED_SIGNED", "DRIVER_RELEASED", "NO_ONE_HOME",
    "REFUSED", "ADDRESS_INVALID", "HAZMAT_BLOCKED",
}


def assert_parcel(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    # PRD §3.3: server-minted 12-char alphanumeric uppercase tracker.
    tracking = data.get("tracking_number", "")
    assert isinstance(tracking, str) and len(tracking) == 12, \
        f"tracking_number must be 12 chars, got {tracking!r}"
    assert re.match(r"^[A-Z0-9]{12}$", tracking) is not None, \
        "tracking_number must be uppercase letters and digits only"
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("destination_address_id", ""))
    assert is_valid_uuid(data.get("origin_center_id", ""))
    assert isinstance(data.get("weight_kg"), (int, float))
    assert 0.0 < data["weight_kg"] <= 70.0
    assert isinstance(data.get("declared_value"), (int, float))
    assert 0.0 <= data["declared_value"] <= 50000.0
    assert isinstance(data.get("signature_required"), bool)
    assert data.get("hazmat_class") in HAZMAT_CLASSES
    assert is_iso8601_timestamp(data.get("time_window_start", ""))
    assert is_iso8601_timestamp(data.get("time_window_end", ""))
    assert data.get("status") in PARCEL_STATUSES, \
        f"Parcel.status must be one of {PARCEL_STATUSES}, " \
        f"got {data.get('status')!r}"
    assert isinstance(data.get("redelivery_attempts"), int) \
        and data["redelivery_attempts"] >= 0
    assert isinstance(data.get("quoted_fee"), (int, float)) \
        and data["quoted_fee"] >= 0
    assert_cost_precision(data["quoted_fee"])
    # PRD §3.3: final_fee unset until terminalization.
    if data.get("final_fee") is not None:
        assert isinstance(data["final_fee"], (int, float))
        assert_cost_precision(data["final_fee"])
    assert data.get("last_attempt_outcome") in LAST_ATTEMPT_OUTCOMES


# ---------------------------------------------------------------------------
# Route — PRD §3.4
# ---------------------------------------------------------------------------
ROUTE_STATUSES = {"PLANNED", "DISPATCHED", "IN_PROGRESS",
                  "CLOSED", "CANCELLED"}


def assert_route(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("center_id", ""))
    assert is_valid_uuid(data.get("driver_id", ""))
    assert isinstance(data.get("planned_date"), str) \
        and re.match(r"^\d{4}-\d{2}-\d{2}$", data["planned_date"]) is not None
    assert data.get("status") in ROUTE_STATUSES, \
        f"Route.status must be one of {ROUTE_STATUSES}, " \
        f"got {data.get('status')!r}"
    assert isinstance(data.get("total_distance_km"), (int, float)) \
        and data["total_distance_km"] >= 0
    # PRD §2.8: 'Distances are likewise carried to two decimal places'.
    assert_cost_precision(data["total_distance_km"])
    assert isinstance(data.get("stop_count"), int) \
        and data["stop_count"] >= 0
    assert isinstance(data.get("hazmat_present"), bool)


# ---------------------------------------------------------------------------
# RouteStop — PRD §3.4 / PRD §2.4 lean
# ---------------------------------------------------------------------------
ROUTE_STOP_STATUSES = {"PLANNED", "ARRIVED", "COMPLETED",
                       "FAILED", "SKIPPED"}


def assert_route_stop(data: Dict[str, Any]) -> None:
    assert_lean_fields(data)
    assert is_valid_uuid(data.get("route_id", ""))
    assert is_valid_uuid(data.get("parcel_id", ""))
    assert isinstance(data.get("sequence"), int) and data["sequence"] >= 1
    assert is_iso8601_timestamp(data.get("planned_arrival", ""))
    assert is_iso8601_timestamp(data.get("planned_departure", ""))
    assert data.get("status") in ROUTE_STOP_STATUSES, \
        f"RouteStop.status must be one of {ROUTE_STOP_STATUSES}, " \
        f"got {data.get('status')!r}"
    assert "updated_at" not in data, \
        "RouteStop must NOT carry updated_at (PRD §2.4 — lean entity)"
    assert "version" not in data, \
        "RouteStop must NOT carry version (PRD §2.4 — lean entity)"


# ---------------------------------------------------------------------------
# DeliveryAttempt — PRD §3.5 / PRD §2.4 lean
# ---------------------------------------------------------------------------
ATTEMPT_OUTCOMES = {
    "DELIVERED_SIGNED", "DRIVER_RELEASED", "NO_ONE_HOME",
    "REFUSED", "ADDRESS_INVALID", "HAZMAT_BLOCKED",
}


def assert_delivery_attempt(data: Dict[str, Any]) -> None:
    assert_lean_fields(data)
    assert is_valid_uuid(data.get("parcel_id", ""))
    assert is_valid_uuid(data.get("route_stop_id", ""))
    assert is_valid_uuid(data.get("driver_id", ""))
    assert is_iso8601_timestamp(data.get("attempted_at", ""))
    assert data.get("outcome") in ATTEMPT_OUTCOMES, \
        f"outcome must be one of {ATTEMPT_OUTCOMES}, " \
        f"got {data.get('outcome')!r}"
    assert "updated_at" not in data, \
        "DeliveryAttempt must NOT carry updated_at (PRD §2.4 — lean entity)"
    assert "version" not in data, \
        "DeliveryAttempt must NOT carry version (PRD §2.4 — lean entity)"


# ---------------------------------------------------------------------------
# Appointment — PRD §3.5
# ---------------------------------------------------------------------------
APPOINTMENT_STATUSES = {"PENDING", "ACCEPTED", "REJECTED", "SUPERSEDED"}


def assert_appointment(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("parcel_id", ""))
    assert is_iso8601_timestamp(data.get("requested_window_start", ""))
    assert is_iso8601_timestamp(data.get("requested_window_end", ""))
    assert data.get("status") in APPOINTMENT_STATUSES, \
        f"Appointment.status must be one of {APPOINTMENT_STATUSES}, " \
        f"got {data.get('status')!r}"
    assert isinstance(data.get("fee_charged"), (int, float)) \
        and data["fee_charged"] >= 0
    assert_cost_precision(data["fee_charged"])


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_version_incremented_by(updated: Dict[str, Any],
                                  baseline_version: int,
                                  delta: int = 1) -> None:
    """PRD §2.4: 'a system-managed counter that increments by one on
    every mutation to the resource'."""
    assert updated.get("version") == baseline_version + delta, \
        f"version expected {baseline_version + delta} " \
        f"(baseline {baseline_version} + delta {delta}), " \
        f"got {updated.get('version')!r}"


__all__ = [
    "assert_common_fields",
    "assert_lean_fields",
    "assert_customer",
    "assert_address",
    "assert_transit_center",
    "assert_driver",
    "assert_parcel",
    "assert_route",
    "assert_route_stop",
    "assert_delivery_attempt",
    "assert_appointment",
    "assert_version_incremented_by",
]
