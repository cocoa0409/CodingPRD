"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_station(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["brand"], str)
    assert isinstance(data["tax_rate_bp"], int)
    assert isinstance(data["cash_variance_tolerance_cents"], int)
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_fuel_grade(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["code"] in ["REGULAR", "MIDGRADE", "PREMIUM", "DIESEL"]
    assert isinstance(data["current_price_cents"], int)
    assert isinstance(data["prior_price_cents"], int)
    assert isinstance(data["version"], int)


def assert_tank(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ["ACTIVE", "DOWN"]
    assert isinstance(data["low_stock"], bool)
    assert isinstance(data["version"], int)


def assert_pump(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ["IDLE", "DISPENSING", "OUT_OF_SERVICE"]
    assert isinstance(data["number"], int)
    assert isinstance(data["version"], int)


def assert_delivery(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ["DRAFT", "POSTED", "VOIDED", "REJECTED"]
    assert isinstance(data["invoice_total_cents"], int)
    assert isinstance(data["version"], int)


def assert_shift(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["lifecycle_status"] in ["OPEN", "COUNTING", "CLOSED"]
    assert data["reconcile_status"] in ["PENDING", "BALANCED", "OVER", "SHORT"]
    assert isinstance(data["expected_drawer_cents"], int)
    assert isinstance(data["version"], int)


def assert_fuel_transaction(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["payment_status"] in ["AUTHORIZED", "CAPTURED", "REFUNDED"]
    assert data["settlement_status"] in ["UNSETTLED", "SETTLED", "REVERSED"]
    assert data["tender"] in ["CASH", "CARD"]
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["version"], int)


def assert_store_transaction(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["settlement_status"] in ["SETTLED", "REVERSED"]
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["tax_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["version"], int)


def assert_loyalty_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["tier"] in ["BRONZE", "SILVER", "GOLD"]
    assert isinstance(data["point_balance"], int)
    assert isinstance(data["lifetime_points"], int)
    assert isinstance(data["version"], int)


def assert_car_wash_code(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["package"] in ["BASIC", "DELUXE", "SUPREME"]
    assert data["status"] in ["ISSUED", "REDEEMED", "EXPIRED"]
    assert isinstance(data["price_cents"], int)
    assert isinstance(data["version"], int)


def assert_margin_report(data: dict):
    """MarginReport is an ephemeral snapshot: id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["revenue_cents"], int)
    assert isinstance(data["cogs_cents"], int)
    assert isinstance(data["margin_cents"], int)
