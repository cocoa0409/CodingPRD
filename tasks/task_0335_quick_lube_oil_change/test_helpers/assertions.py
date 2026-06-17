"""Entity assertions and domain invariant checkers for the Quick Lube & Oil Change API.

Each assert_{entity}() validates the response structure against the PRD contract.
Generic structural validators (UUID/timestamp format) come from the framework.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version present and well-formed (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_shop(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["tax_rate"], (int, float))
    assert 0 <= data["tax_rate"] < 1
    assert isinstance(data["target_throughput_seconds"], int) and data["target_throughput_seconds"] > 0
    assert isinstance(data["max_discount_pct"], (int, float))
    assert isinstance(data["open_bay_count"], int) and data["open_bay_count"] >= 0
    assert data["status"] in ("OPEN", "CLOSED")


def assert_service_package(data: dict):
    _assert_common(data)
    assert data["oil_grade"] in ("CONVENTIONAL", "SYNTHETIC_BLEND", "FULL_SYNTHETIC", "HIGH_MILEAGE")
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert isinstance(data["included_quarts"], int) and data["included_quarts"] > 0
    assert isinstance(data["labor_minutes"], int) and data["labor_minutes"] > 0
    assert isinstance(data["interval_miles"], int) and data["interval_miles"] > 0
    assert isinstance(data["interval_days"], int) and data["interval_days"] > 0
    assert isinstance(data["requires_synthetic_certified_bay"], bool)
    assert isinstance(data["active"], bool)


def assert_inspection_item(data: dict):
    _assert_common(data)
    assert data["code"] in ("AIR_FILTER", "CABIN_FILTER", "WIPER_BLADES", "COOLANT_FLUSH", "TRANSMISSION_FLUSH")
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert isinstance(data["labor_minutes"], int) and data["labor_minutes"] >= 0
    assert isinstance(data["active"], bool)


def assert_coupon(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["discount_type"] in ("PERCENT", "FLAT")
    assert isinstance(data["usage_limit"], int) and data["usage_limit"] > 0
    assert isinstance(data["redeemed_count"], int) and data["redeemed_count"] >= 0
    assert data["status"] in ("ACTIVE", "EXHAUSTED", "EXPIRED")


def assert_fleet_account(data: dict):
    _assert_common(data)
    assert isinstance(data["company_name"], str) and len(data["company_name"]) > 0
    assert isinstance(data["discount_pct"], (int, float)) and 0 <= data["discount_pct"] < 1
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert isinstance(data["reserved_credit_cents"], int)
    assert isinstance(data["settled_credit_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")


def assert_vehicle(data: dict):
    _assert_common(data)
    assert isinstance(data["vin"], str) and len(data["vin"]) > 0
    assert isinstance(data["odometer"], int) and data["odometer"] >= 0
    assert isinstance(data["service_due"], bool)


def assert_bay(data: dict):
    _assert_common(data)
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert isinstance(data["synthetic_certified"], bool)
    assert data["status"] in ("OPEN", "OCCUPIED", "CLOSED")


def assert_technician(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["synthetic_certified"], bool)
    assert isinstance(data["cleanup_buffer_seconds"], int) and data["cleanup_buffer_seconds"] >= 0
    assert isinstance(data["active"], bool)


def assert_queue_ticket(data: dict):
    _assert_common(data)
    assert isinstance(data["queue_seq"], int)
    assert data["status"] in ("WAITING", "ASSIGNED", "IN_BAY", "DONE", "CANCELLED")


def assert_work_order(data: dict):
    _assert_common(data)
    assert isinstance(data["odometer_in"], int) and data["odometer_in"] >= 0
    assert isinstance(data["package_price_cents"], int)
    assert isinstance(data["lines_total_cents"], int)
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["coupon_discount_cents"], int)
    assert isinstance(data["fleet_discount_cents"], int)
    assert isinstance(data["total_discount_cents"], int)
    assert isinstance(data["tax_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["service_status"] in ("DRAFT", "IN_SERVICE", "INSPECTION", "READY", "COMPLETED", "CANCELLED")
    assert data["payment_status"] in ("UNPAID", "AUTHORIZED", "PAID", "VOIDED")


def assert_work_order_pricing_consistent(data: dict):
    """Pricing identities that must hold on any work order (PRD §3.6)."""
    assert data["subtotal_cents"] == data["package_price_cents"] + data["lines_total_cents"], (
        "subtotal_cents must equal package_price_cents + lines_total_cents"
    )
    taxable = data["subtotal_cents"] - data["total_discount_cents"]
    assert data["total_cents"] == taxable + data["tax_cents"], (
        "total_cents must equal (subtotal - total_discount) + tax"
    )
    assert data["total_discount_cents"] >= 0
    assert data["total_cents"] >= 0


def assert_work_order_line(data: dict):
    _assert_common(data)
    assert data["code"] in ("AIR_FILTER", "CABIN_FILTER", "WIPER_BLADES", "COOLANT_FLUSH", "TRANSMISSION_FLUSH")
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert isinstance(data["labor_minutes"], int)
    assert isinstance(data["voided"], bool)


def assert_service_sticker(data: dict):
    """ServiceSticker is immutable: id + created_at only, no updated_at / version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "sticker id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "sticker created_at must be ISO 8601"
    assert "version" not in data, "ServiceSticker must not carry a version field"
    assert "updated_at" not in data, "ServiceSticker must not carry an updated_at field"
    assert data["basis"] in ("MILEAGE", "TIME")


def assert_payment(data: dict):
    _assert_common(data)
    assert data["method"] in ("CARD", "CASH", "FLEET_ACCOUNT")
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("AUTHORIZED", "CAPTURED", "VOIDED")
