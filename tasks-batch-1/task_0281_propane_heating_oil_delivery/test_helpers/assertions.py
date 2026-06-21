"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates structural shape (UUID id, ISO 8601 timestamps,
field types and enum membership) per the PRD. Immutable observations
(TankMonitorReading, DegreeDayReading) carry only id + created_at — their
assertions deliberately do NOT require updated_at or version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_ACCOUNT_STATUSES = ["ACTIVE", "SUSPENDED", "CLOSED"]
_PLAN_TYPES = ["FIXED", "CAP", "MARKET"]
_PLAN_STATUSES = ["DRAFT", "ACTIVE", "EXPIRED"]
_FUEL_TYPES = ["PROPANE", "HEATING_OIL"]
_TANK_SERVICE_STATUSES = ["IN_SERVICE", "LOCKED_OUT", "DECOMMISSIONED"]
_REORDER_STATUSES = ["OK", "DUE"]
_DELIVERY_MODES = ["WILL_CALL", "AUTOMATIC"]
_MARKET_STATUSES = ["ACTIVE", "EXPIRED"]
_LEASE_STATUSES = ["ACTIVE", "TERMINATED"]
_INSPECTION_RESULTS = ["PASSED", "FAILED"]
_ROUTE_STATUSES = ["PLANNING", "DISPATCHED", "COMPLETED", "CANCELLED"]
_ORDER_ORIGINS = ["WILL_CALL", "AUTOMATIC"]
_ORDER_PRIORITIES = ["STANDARD", "EMERGENCY"]
_ORDER_STATUSES = ["CREATED", "SCHEDULED", "HOLD", "DELIVERED", "CANCELLED"]
_BUDGET_STATUSES = ["ACTIVE", "RECONCILED"]


def _assert_common_quartet(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 and increments"


def _assert_lean_pair(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "immutable observation must not carry updated_at"
    assert "version" not in data, "immutable observation must not carry version"


def assert_account(data: dict):
    _assert_common_quartet(data)
    assert isinstance(data["customer_name"], str) and len(data["customer_name"]) > 0
    assert isinstance(data["region_code"], str) and len(data["region_code"]) > 0
    assert data["fuel_type"] in _FUEL_TYPES, f"fuel_type {data['fuel_type']!r}"
    assert data["service_status"] in _ACCOUNT_STATUSES, f"service_status {data['service_status']!r}"
    assert isinstance(data["credit_balance_cents"], int)


def assert_price_plan(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data["account_id"]), "account_id must be a UUID"
    assert data["plan_type"] in _PLAN_TYPES, f"plan_type {data['plan_type']!r}"
    assert data["status"] in _PLAN_STATUSES, f"status {data['status']!r}"


def assert_tank(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data["account_id"]), "account_id must be a UUID"
    assert isinstance(data["capacity_gallons"], int) and data["capacity_gallons"] >= 1
    assert isinstance(data["current_gallons"], int) and data["current_gallons"] >= 0
    assert isinstance(data["reorder_threshold_pct"], int)
    assert 1 <= data["reorder_threshold_pct"] <= 99
    assert isinstance(data["k_factor"], int) and data["k_factor"] >= 1
    assert data["delivery_mode"] in _DELIVERY_MODES, f"delivery_mode {data['delivery_mode']!r}"
    assert isinstance(data["monitor_installed"], bool)
    assert data["service_status"] in _TANK_SERVICE_STATUSES, f"service_status {data['service_status']!r}"
    assert data["reorder_status"] in _REORDER_STATUSES, f"reorder_status {data['reorder_status']!r}"


def assert_tank_monitor_reading(data: dict):
    _assert_lean_pair(data)
    assert is_valid_uuid(data["tank_id"]), "tank_id must be a UUID"
    assert isinstance(data["reading_gallons"], int) and data["reading_gallons"] >= 0
    assert is_iso8601_timestamp(data["read_at"]), "read_at must be ISO 8601"


def assert_degree_day_reading(data: dict):
    _assert_lean_pair(data)
    assert isinstance(data["region_code"], str) and len(data["region_code"]) > 0
    assert is_iso8601_timestamp(data["reading_date"]), "reading_date must be ISO 8601"
    assert isinstance(data["heating_degree_days"], int) and data["heating_degree_days"] >= 0


def assert_market_price(data: dict):
    _assert_common_quartet(data)
    assert isinstance(data["region_code"], str) and len(data["region_code"]) > 0
    assert data["fuel_type"] in _FUEL_TYPES, f"fuel_type {data['fuel_type']!r}"
    assert isinstance(data["market_price_cents_per_gallon"], int)
    assert data["market_price_cents_per_gallon"] >= 1
    assert data["status"] in _MARKET_STATUSES, f"status {data['status']!r}"


def assert_tank_lease(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data["tank_id"]), "tank_id must be a UUID"
    assert isinstance(data["monthly_rent_cents"], int) and data["monthly_rent_cents"] >= 0
    assert is_iso8601_timestamp(data["lease_start"]), "lease_start must be ISO 8601"
    assert is_iso8601_timestamp(data["lease_end"]), "lease_end must be ISO 8601"
    assert data["status"] in _LEASE_STATUSES, f"status {data['status']!r}"


def assert_safety_inspection(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data["tank_id"]), "tank_id must be a UUID"
    assert data["result"] in _INSPECTION_RESULTS, f"result {data['result']!r}"
    assert is_iso8601_timestamp(data["inspected_at"]), "inspected_at must be ISO 8601"


def assert_truck(data: dict):
    _assert_common_quartet(data)
    assert isinstance(data["region_code"], str) and len(data["region_code"]) > 0
    assert isinstance(data["daily_capacity_gallons"], int) and data["daily_capacity_gallons"] >= 1
    assert isinstance(data["turnaround_buffer_minutes"], int)


def assert_delivery_route(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data["truck_id"]), "truck_id must be a UUID"
    assert is_iso8601_timestamp(data["route_date"]), "route_date must be ISO 8601"
    assert is_iso8601_timestamp(data["window_start"]), "window_start must be ISO 8601"
    assert is_iso8601_timestamp(data["window_end"]), "window_end must be ISO 8601"
    assert data["status"] in _ROUTE_STATUSES, f"status {data['status']!r}"
    assert isinstance(data["reserved_gallons"], int) and data["reserved_gallons"] >= 0


def assert_delivery_order(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data["account_id"]), "account_id must be a UUID"
    assert is_valid_uuid(data["tank_id"]), "tank_id must be a UUID"
    assert data["origin"] in _ORDER_ORIGINS, f"origin {data['origin']!r}"
    assert isinstance(data["requested_gallons"], int) and data["requested_gallons"] >= 1
    assert data["priority"] in _ORDER_PRIORITIES, f"priority {data['priority']!r}"
    assert data["status"] in _ORDER_STATUSES, f"status {data['status']!r}"


def assert_budget_plan(data: dict):
    _assert_common_quartet(data)
    assert is_valid_uuid(data["account_id"]), "account_id must be a UUID"
    assert is_iso8601_timestamp(data["plan_year_start"]), "plan_year_start must be ISO 8601"
    assert isinstance(data["estimated_annual_gallons"], int) and data["estimated_annual_gallons"] >= 1
    assert isinstance(data["estimated_price_cents_per_gallon"], int)
    assert data["estimated_price_cents_per_gallon"] >= 1
    assert isinstance(data["installments_paid_count"], int) and data["installments_paid_count"] >= 0
    assert isinstance(data["actual_cost_to_date_cents"], int)
    assert isinstance(data["settlement_balance_cents"], int)
    assert data["status"] in _BUDGET_STATUSES, f"status {data['status']!r}"


def assert_route_reservation_conserved(route: dict, expected_reserved: int):
    """A route's reserved_gallons is the conserved running sum of requested_gallons
    over the orders currently holding a reservation on it (PRD §2.5, §3.6)."""
    assert route["reserved_gallons"] == expected_reserved, (
        f"reserved_gallons expected {expected_reserved}, got {route['reserved_gallons']}"
    )
