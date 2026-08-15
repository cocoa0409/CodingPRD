"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_practice(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region"], str) and data["region"]
    assert data["practice_tier"] in ("STANDARD", "PREMIER", "ELITE")
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["credit_available_cents"], int)
    assert isinstance(data["sterilization_compliant"], bool)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["kind"] in ("CONSUMABLE", "EQUIPMENT", "PART", "REGULATED")
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["manufacturer"], str) and data["manufacturer"]


def assert_usage_profile(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("practice_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    assert isinstance(data["reorder_point"], (int, float))
    assert isinstance(data["target_stock_level"], (int, float))
    assert isinstance(data["auto_replenish_enabled"], bool)
    assert isinstance(data["average_daily_usage"], (int, float))
    assert isinstance(data["on_hand_estimate"], (int, float))


def assert_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("practice_id", ""))
    assert data["kind"] in ("MANUAL", "AUTO", "STARTUP", "BUNDLE")
    assert data["status"] in ("DRAFT", "SUBMITTED", "DELIVERED", "CANCELLED")
    assert isinstance(data["lines"], list)
    for line in data["lines"]:
        assert is_valid_uuid(line.get("product_id", ""))
        assert isinstance(line["quantity"], int) and line["quantity"] > 0
        assert isinstance(line["unit_price_cents"], int)
        assert isinstance(line["line_total_cents"], int)
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["volume_discount_cents"], int)
    assert isinstance(data["bundle_discount_cents"], int)
    assert isinstance(data["discount_cents"], int)
    assert isinstance(data["total_cents"], int)


def assert_equipment_sale(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("practice_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    assert isinstance(data["sale_price_cents"], int)
    assert data["status"] in (
        "QUOTE", "CONFIRMED", "INSTALL_SCHEDULED", "INSTALLED", "TRAINED", "ACCEPTED",
    )
    assert isinstance(data["install_rework_count"], int)


def assert_technician(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region"], str) and data["region"]
    assert isinstance(data["certifications"], list)
    for cert in data["certifications"]:
        assert cert in ("INSTALL", "REPAIR", "STERILIZATION")
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["van_stock"], list)


def assert_service_ticket(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("practice_id", ""))
    assert is_valid_uuid(data.get("equipment_sale_id", ""))
    assert data["status"] in (
        "OPEN", "COVERAGE_ASSESSED", "AWAITING_APPROVAL", "DISPATCHED", "RESOLVED", "CLOSED",
    )


def assert_dispatch_job(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("service_ticket_id", ""))
    assert is_valid_uuid(data.get("technician_id", ""))
    assert data["status"] in ("SCHEDULED", "COMPLETED")


def assert_coverage_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("practice_id", ""))
    assert is_valid_uuid(data.get("equipment_sale_id", ""))
    assert data["coverage_type"] in ("WARRANTY", "SERVICE_PLAN")
    assert data["status"] in ("ACTIVE", "EXPIRED", "EXHAUSTED")
    assert isinstance(data["used_cents"], int)


def assert_promotion(data: dict):
    _assert_common(data)
    assert data["promo_kind"] in ("BUNDLE_DISCOUNT", "MANUFACTURER_REBATE")
    assert data["status"] in ("ACTIVE", "EXPIRED", "EXHAUSTED")


def assert_rebate_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("practice_id", ""))
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("promotion_id", ""))
    assert isinstance(data["claim_amount_cents"], int)
    assert data["status"] in ("DRAFT", "SUBMITTED", "DENIED", "PAID")


def assert_trade_in(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("practice_id", ""))
    assert isinstance(data["equipment_age_months"], int)
    assert data["condition"] in ("WORKING", "NEEDS_REPAIR", "SCRAP")
    assert isinstance(data["category_base_value_cents"], int)
    assert data["status"] in ("REQUESTED", "APPRAISED", "ACCEPTED", "CREDITED", "DISPOSED")


def van_stock_quantity(technician: dict, product_id: str) -> int:
    """Return the quantity_on_van for product_id on this technician (0 when absent)."""
    for entry in technician.get("van_stock", []):
        if entry.get("product_id") == product_id:
            return entry.get("quantity_on_van", 0)
    return 0
