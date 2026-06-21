"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["service_zip"], str)
    assert isinstance(data["wallet_credit_cents"], int)


def assert_property(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["address"], str)
    assert isinstance(data["lawn_area_sqft"], int)
    assert isinstance(data["zip"], str)


def assert_preference(data: dict):
    _assert_common(data)
    assert isinstance(data["property_id"], str)
    assert isinstance(data["grass_height_mm"], int)
    assert isinstance(data["fertilization_enabled"], bool)
    assert isinstance(data["snow_opt_out"], bool)


def assert_contract(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "ACTIVE", "SUSPENDED", "CLOSED"]
    assert isinstance(data["contract_price_cents"], int)
    assert isinstance(data["accrued_balance_cents"], int)
    assert data["season"] in ["WINTER", "SUMMER"]


def assert_route(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "DISPATCHED", "CLOSED"]
    assert isinstance(data["last_dispatch_load_minutes"], int)


def assert_route_stop(data: dict):
    _assert_common(data)
    assert isinstance(data["active"], bool)
    assert isinstance(data["sequence"], int)


def assert_crew(data: dict):
    _assert_common(data)
    assert data["status"] in ["AVAILABLE", "ON_DISPATCH", "OFF_DUTY"]


def assert_equipment(data: dict):
    _assert_common(data)
    assert data["status"] in ["IDLE", "IN_SERVICE", "MAINTENANCE_DUE", "UNDER_MAINTENANCE"]
    assert data["equipment_type"] in ["PLOW", "MOWER", "SPREADER"]
    assert isinstance(data["wear_score"], int)


def assert_visit(data: dict):
    _assert_common(data)
    assert data["status"] in ["SCHEDULED", "DISPATCHED", "COMPLETED", "SKIPPED", "CANCELLED"]
    assert data["service_type"] in ["LAWN", "SNOW", "FERTILIZATION"]
    assert isinstance(data["surcharge_cents"], int)


def assert_skip_request(data: dict):
    _assert_common(data)
    assert data["status"] in ["PENDING", "APPROVED", "REJECTED"]
    assert isinstance(data["credit_cents"], int)


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in ["ISSUED", "PAID", "VOID"]
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["tax_cents"], int)
    assert isinstance(data["total_due_cents"], int)


def assert_weather_reading(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    # WeatherReading is immutable: no updated_at, no version.
    assert "updated_at" not in data, "WeatherReading must not carry updated_at"
    assert "version" not in data, "WeatherReading must not carry version"
    assert isinstance(data["processed"], bool)
