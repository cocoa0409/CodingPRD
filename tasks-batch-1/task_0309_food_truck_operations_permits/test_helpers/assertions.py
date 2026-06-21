"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the response structure against the PRD contract,
using the framework's generic format checkers internally.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """id + created_at + updated_at + integer version for a full-record entity."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 and increments"


def assert_commissary(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["state_code"], str)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["docked_truck_count"], int)
    assert data["docked_truck_count"] >= 0


def assert_health_permit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("truck_id", "")), "truck_id must be a UUID"
    assert isinstance(data["permit_number"], str)
    assert data["status"] in ("ACTIVE", "EXPIRED", "REVOKED")
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["expires_at"])


def assert_truck(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("commissary_id", "")), "commissary_id must be a UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["operability"] in ("OPERABLE", "RESTRICTED", "GROUNDED")
    assert isinstance(data["propane_psi"], (int, float)) and data["propane_psi"] >= 0
    assert isinstance(data["generator_runtime_hours"], (int, float))
    assert data["generator_runtime_hours"] >= 0
    assert isinstance(data["reservation_fee_balance_cents"], int)
    assert data["reservation_fee_balance_cents"] >= 0, "fee balance is always non-negative"
    assert isinstance(data["gross_sales_cents"], int)


def assert_menu_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("truck_id", ""))
    assert isinstance(data["sku"], str)
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["par_units"], int) and data["par_units"] >= 0
    assert isinstance(data["prepared_units"], int) and data["prepared_units"] >= 0
    assert data["status"] in ("AVAILABLE", "UNLISTED")


def assert_prep_batch(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("truck_id", ""))
    assert is_valid_uuid(data.get("menu_item_id", ""))
    assert isinstance(data["units_made"], int) and data["units_made"] >= 1
    assert data["status"] in ("OPEN", "DISCARDED")


def assert_spot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["concurrent_capacity"], int) and data["concurrent_capacity"] >= 1
    assert isinstance(data["buffer_minutes"], int) and data["buffer_minutes"] >= 0
    assert isinstance(data["reservation_fee_cents"], int) and data["reservation_fee_cents"] >= 0


def assert_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str)
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert data["status"] in ("SCHEDULED", "CANCELLED")


def assert_booking(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("truck_id", ""))
    assert is_valid_uuid(data.get("spot_id", ""))
    assert is_valid_uuid(data.get("event_id", ""))
    assert data["status"] in ("RESERVED", "ARRIVED", "DEPARTED", "NO_SHOW", "CANCELLED")
    assert isinstance(data["reservation_fee_cents"], int) and data["reservation_fee_cents"] >= 0
    assert isinstance(data["fee_refunded_cents"], int) and data["fee_refunded_cents"] >= 0


def assert_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("truck_id", ""))
    assert is_valid_uuid(data.get("booking_id", ""))
    assert data["lifecycle_status"] in ("OPEN", "SETTLED", "VOID")
    assert data["payment_status"] in ("UNPAID", "AUTHORIZED", "CAPTURED", "REFUNDED")
    assert isinstance(data["tip_cents"], int) and data["tip_cents"] >= 0
    assert data["discount_code"] in ("NONE", "HAPPY_HOUR", "BULK10")
    assert isinstance(data["live_total_cents"], int) and data["live_total_cents"] >= 0


def assert_order_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("menu_item_id", ""))
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["line_subtotal_cents"], int) and data["line_subtotal_cents"] >= 0


def assert_staff_shift(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("truck_id", ""))
    assert isinstance(data["staff_name"], str)
    assert data["role"] in ("DRIVER", "COOK", "CASHIER")
    assert is_iso8601_timestamp(data["shift_start"])
    assert is_iso8601_timestamp(data["shift_end"])
    assert data["status"] in ("SCHEDULED", "CANCELLED")


def assert_utility_log(data: dict):
    """UtilityLog is append-only: id + created_at only, NO updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only UtilityLog must not carry updated_at"
    assert "version" not in data, "append-only UtilityLog must not carry version"
    assert is_valid_uuid(data.get("truck_id", ""))
    assert data["utility"] in ("PROPANE", "GENERATOR")
