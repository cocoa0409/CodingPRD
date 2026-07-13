"""Entity assertions, numeric-precision helpers and domain invariant checkers."""

from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

# Tolerances chosen so that a value rounded to the PRD's decimal place passes and an
# un-rounded / differently-rounded value fails.
MONEY_TOL = 0.002  # money carries 2 decimal places (PRD §2.8)
PCT_TOL = 0.02  # energy / risk / health percentages carry 1 decimal place
KM_TOL = 0.0005  # distances carry 3 decimal places
HOURS_TOL = 0.002  # accumulated airframe hours carry 2 decimal places


# ------------------------------------------------------------------ time helpers
def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp, tolerating 'Z' and optional fractional digits."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 timestamp, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant(actual: str, expected_iso: str, label: str = "timestamp") -> None:
    """Compare two ISO 8601 instants by value, not by string form."""
    got = parse_instant(actual)
    want = parse_instant(expected_iso)
    assert got == want, f"Expected {label} == {expected_iso}, got {actual}"


# --------------------------------------------------------------- numeric helpers
def assert_money(actual, expected, label="amount") -> None:
    assert actual == pytest.approx(expected, abs=MONEY_TOL), (
        f"Expected {label} == {expected} (2 dp, half up), got {actual}"
    )


def assert_pct(actual, expected, label="percentage") -> None:
    assert actual == pytest.approx(expected, abs=PCT_TOL), (
        f"Expected {label} == {expected} (1 dp, half up), got {actual}"
    )


def assert_km(actual, expected, label="distance_km") -> None:
    assert actual == pytest.approx(expected, abs=KM_TOL), (
        f"Expected {label} == {expected} (3 dp, half up), got {actual}"
    )


def assert_hours(actual, expected, label="hours") -> None:
    assert actual == pytest.approx(expected, abs=HOURS_TOL), (
        f"Expected {label} == {expected} (2 dp, half up), got {actual}"
    )


# ------------------------------------------------------------- common structure
def assert_common_fields(data: dict, entity: str = "resource") -> None:
    """id + created_at + updated_at + version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 timestamp: {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 timestamp: {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1, got {data.get('version')!r}"
    )


def assert_immutable_fields(data: dict, entity: str = "resource") -> None:
    """Immutable resources carry id + created_at ONLY — no updated_at, no version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 timestamp"
    )
    assert "version" not in data, f"{entity} must not expose a version field, got {data.get('version')!r}"
    assert "updated_at" not in data, (
        f"{entity} must not expose an updated_at field, got {data.get('updated_at')!r}"
    )


# ------------------------------------------------------------ entity assertions
def assert_service_area(data: dict) -> None:
    assert_common_fields(data, "ServiceArea")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["name"], str) and data["name"]


def assert_nest(data: dict) -> None:
    assert_common_fields(data, "Nest")
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["pad_count"], int) and data["pad_count"] >= 1
    assert isinstance(data["reserved_pads"], int) and data["reserved_pads"] >= 0


def assert_drone(data: dict) -> None:
    assert_common_fields(data, "Drone")
    assert data["status"] in ("IDLE", "RESERVED", "IN_FLIGHT", "GROUNDED")
    assert data["airframe_class"] in ("LIGHT", "HEAVY")
    assert isinstance(data["advisory_risk_score"], (int, float))
    assert isinstance(data["blocking_risk_score"], (int, float))
    assert data["blocking_risk_score"] >= data["advisory_risk_score"], (
        "blocking_risk_score is always at least advisory_risk_score on identical data"
    )


def assert_battery(data: dict) -> None:
    assert_common_fields(data, "Battery")
    assert data["state"] in ("CHARGING", "READY", "IN_USE", "COOLDOWN", "RETIRED")
    assert 0 <= data["charge_pct"] <= 100
    assert isinstance(data["cycle_count"], int) and data["cycle_count"] >= 0
    assert data["health_pct"] >= 0, "health_pct is floored at zero"


def assert_customer(data: dict) -> None:
    assert_common_fields(data, "Customer")
    assert data["held_total"] >= 0
    assert data["billed_total"] >= 0


def assert_order(data: dict) -> None:
    assert_common_fields(data, "Order")
    assert data["status"] in ("QUOTED", "ASSIGNED", "IN_TRANSIT", "DELIVERED", "CANCELLED")
    assert data["priority"] in ("STANDARD", "URGENT", "MEDICAL")
    assert isinstance(data["payload_weight_g"], int) and data["payload_weight_g"] > 0


def assert_flight(data: dict) -> None:
    assert_common_fields(data, "Flight")
    assert data["ops_state"] in (
        "PLANNED",
        "LAUNCHED",
        "DROPPING",
        "RETURNING",
        "RECOVERED",
        "ABORTED",
    )
    assert data["clearance_state"] in ("UNFILED", "FILED", "CLEARED", "REVOKED")
    assert data["launch_nest_id"] == data["recovery_nest_id"], (
        "a flight's launch_nest_id and recovery_nest_id are always the same nest"
    )


def assert_airspace_authorization(data: dict) -> None:
    assert_common_fields(data, "AirspaceAuthorization")
    assert data["status"] in ("PENDING", "APPROVED", "DENIED", "REVOKED")
    assert 0 < data["requested_alt_ft"] <= 400


def assert_geofence_zone(data: dict) -> None:
    assert_common_fields(data, "GeofenceZone")
    assert data["status"] in ("ACTIVE", "LIFTED")
    assert data["kind"] in ("NO_FLY", "TFR", "WEATHER_HOLD")
    assert data["radius_km"] > 0


def assert_weather_observation(data: dict) -> None:
    assert_immutable_fields(data, "WeatherObservation")
    assert isinstance(data["flyable"], bool)
    assert data["precip"] in ("NONE", "LIGHT", "HEAVY")


def assert_delivery_drop(data: dict) -> None:
    assert_immutable_fields(data, "DeliveryDrop")
    assert 0 < data["hover_alt_ft"] <= 400
    assert isinstance(data["confirmed_by_user_id"], str) and data["confirmed_by_user_id"]


def assert_incident(data: dict) -> None:
    assert_common_fields(data, "Incident")
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "MAINTENANCE_REQUIRED", "CLOSED")
    assert data["severity"] in ("MINOR", "MAJOR", "CRITICAL")


def assert_maintenance_log(data: dict) -> None:
    assert_common_fields(data, "MaintenanceLog")
    assert data["status"] in ("SCHEDULED", "COMPLETED")
    assert data["work_type"] in ("INSPECTION", "REPAIR", "BATTERY_SWAP", "OVERHAUL")


# ------------------------------------------------------------- domain invariants
def assert_funds_ledger(customer: dict, orders: list) -> None:
    """PRD §2.10: held_total == sum(order_total over ASSIGNED|IN_TRANSIT orders);
    billed_total == sum(order_total over DELIVERED orders)."""
    held = sum(o["order_total"] for o in orders if o["status"] in ("ASSIGNED", "IN_TRANSIT"))
    billed = sum(o["order_total"] for o in orders if o["status"] == "DELIVERED")
    assert_money(customer["held_total"], round(held, 2), "held_total")
    assert_money(customer["billed_total"], round(billed, 2), "billed_total")


def assert_pad_ledger(nest: dict, flights: list) -> None:
    """PRD §2.10: reserved_pads == count of flights recovering here whose ops_state is
    PLANNED, LAUNCHED, DROPPING or RETURNING."""
    live = [
        f
        for f in flights
        if f["recovery_nest_id"] == nest["id"]
        and f["ops_state"] in ("PLANNED", "LAUNCHED", "DROPPING", "RETURNING")
    ]
    assert nest["reserved_pads"] == len(live), (
        f"Expected reserved_pads == {len(live)} (live sorties recovering at this nest), "
        f"got {nest['reserved_pads']}"
    )
