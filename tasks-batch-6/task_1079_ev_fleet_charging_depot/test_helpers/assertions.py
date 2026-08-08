"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_depot(data: dict):
    _common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["max_load_kw"] > 0
    assert data["contracted_capacity_kw"] > 0
    assert isinstance(data["tariff_windows"], list) and data["tariff_windows"]
    assert data["reserved_load_kw"] >= 0
    assert isinstance(data["reimbursement_committed_cents"], int)
    assert data["reimbursement_committed_cents"] >= 0


def assert_charger(data: dict):
    _common(data)
    assert data["connector_type"] in ("CCS", "CHADEMO", "J1772", "NACS")
    assert data["max_power_kw"] > 0
    assert data["service_status"] in ("OPERATIONAL", "DOWN")


def assert_vehicle(data: dict):
    _common(data)
    assert data["connector_type"] in ("CCS", "CHADEMO", "J1772", "NACS")
    assert data["battery_capacity_kwh"] > 0
    assert 0 <= data["current_soc_pct"] <= 100
    assert data["status"] in ("IN_SERVICE", "GROUNDED")
    assert data["readiness_status"] in ("READY", "NOT_READY")


def assert_driver(data: dict):
    _common(data)
    assert isinstance(data["home_tariff_cents_per_kwh"], int)


def assert_charge_session(data: dict):
    _common(data)
    assert data["status"] in ("SCHEDULED", "ACTIVE", "COMPLETED", "CANCELLED", "INTERRUPTED")
    assert data["power_kw"] > 0
    assert isinstance(data["estimated_cost_cents"], int)
    assert isinstance(data["final_cost_cents"], int)


def assert_telemetry_reading(data: dict):
    # TelemetryReading is append-only: only id + created_at as common fields.
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "TelemetryReading must not carry updated_at"
    assert "version" not in data, "TelemetryReading must not carry version"


def assert_work_order(data: dict):
    _common(data)
    assert data["asset_type"] in ("CHARGER", "VEHICLE")
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH")
    assert data["status"] in ("OPEN", "IN_PROGRESS", "ON_HOLD", "RESOLVED", "CLOSED")
    assert isinstance(data["downtime_minutes"], int)


def assert_route_assignment(data: dict):
    _common(data)
    assert data["status"] in ("PLANNED", "ASSIGNED", "COMPLETED", "CANCELLED")
    assert data["distance_km"] > 0
    assert 0 <= data["required_soc_pct"] <= 100


def assert_reimbursement_claim(data: dict):
    _common(data)
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED", "PAID")
    assert isinstance(data["committed_amount_cents"], int)
    assert isinstance(data["estimated_amount_cents"], int)


def assert_invoice(data: dict):
    _common(data)
    assert data["status"] in ("DRAFT", "ISSUED", "PAID")
    assert isinstance(data["energy_subtotal_cents"], int)
    assert isinstance(data["demand_charge_cents"], int)
    assert isinstance(data["total_cents"], int)
