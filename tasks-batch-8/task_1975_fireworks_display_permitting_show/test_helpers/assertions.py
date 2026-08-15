"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)


def assert_operator(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("legal_name"), str) and len(data["legal_name"]) > 0
    assert isinstance(data.get("atf_license_number"), str)
    assert data.get("license_class") in ["DISPLAY_1_3G", "PROXIMATE_1_4G"]
    assert data.get("status") in ["ACTIVE", "SUSPENDED"]
    assert "version" in data and isinstance(data["version"], int)


def assert_crew_member(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("full_name"), str) and len(data["full_name"]) > 0
    assert data.get("cert_level") in ["TRAINEE", "SHOOTER", "LEAD_OPERATOR"]
    assert "version" in data and isinstance(data["version"], int)


def assert_display_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data.get("venue_id"), str)
    assert data.get("status") in [
        "DRAFT", "SUBMITTED", "REVISION_REQUESTED", "APPROVED",
        "STANDBY_CONFIRMED", "READY", "IN_PROGRESS", "SHOW_COMPLETE",
        "SWEEP_VERIFIED", "CLOSED", "DENIED", "CANCELLED",
    ]
    assert data.get("weather_decision") in ["PENDING", "GO", "NO_GO"]
    assert isinstance(data.get("dud_count"), int)
    assert isinstance(data.get("fired_count"), int)
    assert "version" in data and isinstance(data["version"], int)


def assert_site_plan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data.get("status") in ["CURRENT", "SUPERSEDED"]
    assert isinstance(data.get("required_spectator_distance_ft"), int)
    assert "version" in data and isinstance(data["version"], int)


def assert_permit_application(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data.get("status") in ["SUBMITTED", "INFO_REQUESTED", "APPROVED", "DENIED", "WITHDRAWN"]
    assert isinstance(data.get("planned_hours"), int)
    assert isinstance(data.get("provisional_standby_fee_cents"), int)
    assert "version" in data and isinstance(data["version"], int)


def assert_magazine(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data.get("magazine_type") in ["INDOOR", "OUTDOOR"]
    assert data.get("posture") in ["ACTIVE", "LAPSED"]
    assert_cost_precision(data.get("current_new_lbs", 0), 2)
    assert "version" in data and isinstance(data["version"], int)


def assert_product_batch(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data.get("status") in ["IN_MAGAZINE", "CHECKED_OUT", "DEPLETED", "QUARANTINED"]
    for field in ("quantity_units", "quantity_remaining", "qty_at_magazine", "qty_at_show", "qty_expended"):
        assert isinstance(data.get(field), int), f"{field} must be int"
    assert "version" in data and isinstance(data["version"], int)


def assert_inventory_movement(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data.get("movement_type") in ["CHECK_OUT", "RETURN", "EXPEND"]
    assert isinstance(data.get("quantity"), int)
    # Append-only (PRD §2.4): updated_at and version are absent.
    assert "updated_at" not in data, "InventoryMovement is append-only: updated_at must be absent"
    assert "version" not in data, "InventoryMovement is append-only: version must be absent"


def assert_weather_reading(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data.get("source") in ["ON_SITE_ANEMOMETER", "NWS"]
    # Append-only (PRD §2.4): updated_at and version are absent.
    assert "updated_at" not in data, "WeatherReading is append-only: updated_at must be absent"
    assert "version" not in data, "WeatherReading is append-only: version must be absent"


def assert_security_post(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data.get("status") in ["UNSTAFFED", "STAFFED", "SECURED", "RELEASED"]
    assert isinstance(data.get("required_guards"), int)
    assert isinstance(data.get("assigned_guards"), int)
    assert "version" in data and isinstance(data["version"], int)


def assert_misfire_record(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data.get("status") in ["LOGGED", "DISPOSED"]
    assert "version" in data and isinstance(data["version"], int)


def assert_sweep_record(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data.get("verdict") in ["PENDING", "VERIFIED", "REJECTED"]
    assert "version" in data and isinstance(data["version"], int)


def assert_incident_report(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data.get("status") in ["FILED", "CLOSED"]
    assert "version" in data and isinstance(data["version"], int)


def assert_batch_unit_accountability(data: dict):
    """PRD §3.4 invariant: quantity_units always equals the sum of
    qty_at_magazine, qty_at_show, and qty_expended."""
    total = data["qty_at_magazine"] + data["qty_at_show"] + data["qty_expended"]
    assert total == data["quantity_units"], (
        f"Unit accountability broken: {data['qty_at_magazine']} + "
        f"{data['qty_at_show']} + {data['qty_expended']} = {total} != {data['quantity_units']}"
    )
    assert data["quantity_remaining"] == data["quantity_units"] - data["qty_expended"]
