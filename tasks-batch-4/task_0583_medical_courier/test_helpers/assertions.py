"""Entity assertions and domain invariant checkers for the Medical Courier API."""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .constants import SLA_MINUTES


# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------
def parse_instant(value: str) -> datetime:
    """Parse an ISO-8601 UTC instant, tolerating both 'Z' and '+00:00' suffixes
    and any number of fractional digits."""
    assert isinstance(value, str) and value, f"Expected an ISO 8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected_iso: str, label: str = "timestamp"):
    """Compare two ISO-8601 instants by value, not by string spelling."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"Expected {label} {expected_iso}, got {actual}"
    )


def assert_common_fields(data: dict, entity: str):
    """id / created_at / updated_at / version — the PRD §2.4 common properties."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 timestamp, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 timestamp, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"{entity}.version must be an integer, got {data.get('version')!r}"
    )


# ---------------------------------------------------------------------------
# Entity assertions
# ---------------------------------------------------------------------------
def assert_rate_card(data: dict):
    assert_common_fields(data, "RateCard")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["per_stop_fee_cents"], int) and data["per_stop_fee_cents"] >= 0
    assert isinstance(data["per_mile_rate_cents"], int) and data["per_mile_rate_cents"] >= 0
    assert float(data["stat_surcharge_pct"]) >= 0
    assert isinstance(data["stat_surcharge_cap_cents"], int) and data["stat_surcharge_cap_cents"] >= 0
    assert isinstance(data["temp_handling_fee_cents"], int) and data["temp_handling_fee_cents"] >= 0


def assert_lab_client(data: dict):
    assert_common_fields(data, "LabClient")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["budget_cents"], int) and data["budget_cents"] >= 0
    assert isinstance(data["billed_balance_cents"], int), "billed_balance_cents must be integer cents"


def assert_driver(data: dict):
    assert_common_fields(data, "Driver")
    assert isinstance(data["name"], str) and data["name"]
    assert data["credential_type"] in ("STANDARD", "BLOODBORNE", "HAZMAT")
    assert is_iso8601_timestamp(data["credential_expiry"])
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_vehicle(data: dict):
    assert_common_fields(data, "Vehicle")
    assert isinstance(data["plate"], str) and data["plate"]
    assert isinstance(data["has_refrigeration"], bool)
    assert isinstance(data["sanitation_buffer_minutes"], int)
    assert data["status"] in ("AVAILABLE", "IN_USE")


def assert_route(data: dict):
    assert_common_fields(data, "Route")
    assert is_valid_uuid(data["lab_client_id"])
    assert is_valid_uuid(data["rate_card_id"])
    assert data["run_type"] in ("STAT", "SCHEDULED")
    assert is_iso8601_timestamp(data["scheduled_start"])
    assert is_iso8601_timestamp(data["scheduled_end"])
    assert float(data["planned_total_miles"]) >= 0
    assert data["status"] in ("PLANNED", "ASSIGNED", "DISPATCHED", "COMPLETED")


def assert_stop(data: dict):
    assert_common_fields(data, "Stop")
    assert is_valid_uuid(data["route_id"])
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert isinstance(data["address"], str) and data["address"]
    assert data["stop_kind"] in ("PICKUP", "DROPOFF", "BOTH")
    assert float(data["planned_leg_miles"]) >= 0
    assert data["status"] in ("SCHEDULED", "ARRIVED", "COMPLETED", "MISSED")


def assert_specimen(data: dict):
    assert_common_fields(data, "Specimen")
    assert is_valid_uuid(data["route_id"])
    assert is_valid_uuid(data["pickup_stop_id"])
    assert is_valid_uuid(data["dropoff_stop_id"])
    assert data["specimen_type"] in ("BLOOD", "TISSUE", "URINE", "SWAB", "CULTURE")
    assert data["temp_requirement"] in ("AMBIENT", "REFRIGERATED", "FROZEN")
    assert float(data["required_temp_max_c"]) >= float(data["required_temp_min_c"])
    assert data["custody_status"] in (
        "AWAITING_PICKUP", "IN_TRANSIT", "DELIVERED", "EXCEPTION",
    )
    assert data["integrity_status"] in ("INTACT", "COMPROMISED")
    assert isinstance(data["excursion_count"], int) and data["excursion_count"] >= 0


def assert_scan_event(data: dict):
    """A ScanEvent is append-only (PRD §2.4): only id and created_at, never
    updated_at or version."""
    assert is_valid_uuid(data.get("id", "")), "ScanEvent.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "ScanEvent.created_at must be ISO 8601"
    assert "updated_at" not in data, "ScanEvent must not carry an updated_at field"
    assert "version" not in data, "ScanEvent must not carry a version field"
    assert is_valid_uuid(data["specimen_id"])
    assert is_valid_uuid(data["driver_id"])
    assert is_valid_uuid(data["stop_id"])
    assert data["scan_type"] in ("PICKUP", "DROPOFF")
    assert isinstance(data["is_excursion"], bool)


def assert_route_exception(data: dict):
    assert_common_fields(data, "RouteException")
    assert is_valid_uuid(data["route_id"])
    assert data["exception_type"] in ("MISSED_STOP", "TEMP_EXCURSION", "CREDENTIAL_LAPSE")
    assert isinstance(data["detail"], str) and data["detail"], "RouteException.detail must be present"
    assert data["status"] in ("OPEN", "RESOLVED")


def assert_run_billing(data: dict):
    assert_common_fields(data, "RunBilling")
    assert is_valid_uuid(data["route_id"])
    assert is_valid_uuid(data["lab_client_id"])
    assert isinstance(data["gross_charge_cents"], int)
    assert isinstance(data["surcharge_cents"], int)
    assert isinstance(data["net_charge_cents"], int)
    assert data["status"] in ("DRAFT", "ISSUED", "VOIDED")


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def assert_sla_deadline(route: dict):
    """PRD §3.2: sla_deadline = scheduled_start + 120 min (STAT) / 480 min (SCHEDULED)."""
    expected = parse_instant(route["scheduled_start"]) + timedelta(
        minutes=SLA_MINUTES[route["run_type"]]
    )
    actual = parse_instant(route["sla_deadline"])
    assert actual == expected, (
        f"Expected sla_deadline {expected.isoformat()} for a {route['run_type']} run, got {actual.isoformat()}"
    )


def assert_billing_components_sum(billing: dict):
    """PRD §3.8: net_charge_cents is gross_charge_cents plus surcharge_cents."""
    assert billing["net_charge_cents"] == billing["gross_charge_cents"] + billing["surcharge_cents"], (
        "net_charge_cents must equal gross_charge_cents + surcharge_cents, got "
        f"{billing['net_charge_cents']} != {billing['gross_charge_cents']} + {billing['surcharge_cents']}"
    )
