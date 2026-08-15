"""Entity assertions and lookup helpers (PRD §2.4 common fields, §3 field rules)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

__all__ = [
    "assert_operator",
    "assert_route",
    "assert_product",
    "assert_location",
    "assert_planogram",
    "assert_telemetry_event",
    "assert_order",
    "assert_promotion",
    "assert_credit_claim",
    "assert_service_ticket",
    "assert_availability",
    "find_order_line",
    "find_slot",
    "find_projection_entry",
    "find_claim_line",
]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_operator(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["default_tender"] in ("CASH", "CASHLESS")
    assert isinstance(data["credit_balance_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_route(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["route_code"], str) and data["route_code"]
    assert isinstance(data["delivery_weekdays"], list)
    for day in data["delivery_weekdays"]:
        assert day in ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
    assert isinstance(data["daily_case_capacity"], int)
    assert isinstance(data["min_order_cents"], int)


def assert_product(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["category"] in ("BEVERAGE", "SNACK", "CANDY", "CHILLED", "FROZEN")
    assert isinstance(data["eligible_location_types"], list)
    for lt in data["eligible_location_types"]:
        assert lt in ("OFFICE", "SCHOOL", "HOSPITAL", "GYM")
    assert isinstance(data["case_pack_qty"], int) and data["case_pack_qty"] > 0
    assert isinstance(data["base_price_cents"], int)
    assert isinstance(data["cost_cents"], int)
    assert isinstance(data["shelf_life_days"], int)
    assert data["perishability_class"] in ("AMBIENT", "CHILLED", "FROZEN")
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_location(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("operator_id", "")), "operator_id must be a UUID"
    assert is_valid_uuid(data.get("route_id", "")), "route_id must be a UUID"
    assert data["location_type"] in ("OFFICE", "SCHOOL", "HOSPITAL", "GYM")
    assert isinstance(data["on_hand_projection"], list)


def assert_planogram(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("location_id", "")), "location_id must be a UUID"
    assert data["status"] in ("DRAFT", "ACTIVE", "ARCHIVED")
    assert isinstance(data["slots"], list)
    if data["status"] == "DRAFT":
        assert data.get("activated_at") is None, "DRAFT planogram must not carry activated_at"
    else:
        assert is_iso8601_timestamp(data.get("activated_at", "")), (
            "activated planogram must carry an ISO 8601 activated_at"
        )


def assert_telemetry_event(data: dict):
    # PRD §2.4: the append-only DEX log carries only id and created_at as
    # system fields; updated_at and version must be absent.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "telemetry event must not expose updated_at"
    assert "version" not in data, "telemetry event must not expose version"
    assert is_valid_uuid(data.get("location_id", "")), "location_id must be a UUID"
    assert isinstance(data["recorded_at"], str)
    assert isinstance(data["cash_collected_cents"], int)
    assert isinstance(data["cashless_sales_cents"], int)
    assert isinstance(data["items"], list)


def assert_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("operator_id", "")), "operator_id must be a UUID"
    assert is_valid_uuid(data.get("location_id", "")), "location_id must be a UUID"
    assert is_valid_uuid(data.get("route_id", "")), "route_id must be a UUID"
    assert data["source"] in ("MANUAL", "TELEMETRY_SUGGESTED")
    assert isinstance(data["requested_delivery_date"], str)
    assert isinstance(data["lines"], list)
    assert isinstance(data["total_cases"], int)
    assert isinstance(data["order_total_cents"], int)
    assert isinstance(data["promo_discount_cents"], int)
    assert isinstance(data["amount_due_cents"], int)
    assert isinstance(data["credit_applied_cents"], int)
    assert data["fulfillment_status"] in (
        "DRAFT", "SUBMITTED", "CONFIRMED", "DELIVERED", "CANCELLED",
    )
    assert data["settlement_status"] in ("UNINVOICED", "OPEN", "SETTLED")


def assert_promotion(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be a UUID"
    assert data["discount_type"] in ("PERCENT_OFF", "CENTS_OFF")
    assert isinstance(data["discount_value"], int)
    assert data["stacking_class"] in ("EXCLUSIVE", "STACKABLE")
    assert data["status"] in ("ACTIVE", "TERMINATED")


def assert_credit_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("operator_id", "")), "operator_id must be a UUID"
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert isinstance(data["lines"], list)
    assert isinstance(data["requested_credit_cents"], int)
    assert isinstance(data["applied_cents"], int)
    assert data["status"] in ("SUBMITTED", "APPROVED", "REJECTED", "VOIDED", "SETTLED")


def assert_service_ticket(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("location_id", "")), "location_id must be a UUID"
    assert isinstance(data["equipment_model"], str) and data["equipment_model"]
    assert data["issue_type"] in ("PART_REPLACEMENT", "REPAIR", "PREVENTIVE")
    assert isinstance(data["parts"], list)
    assert isinstance(data["parts_total_cents"], int)
    assert data["status"] in ("OPEN", "SCHEDULED", "COMPLETED")


def assert_availability(data: dict):
    assert isinstance(data["date"], str)
    assert isinstance(data["daily_case_capacity"], int)
    assert isinstance(data["firm_consumed_cases"], int)
    assert isinstance(data["optimistic_consumed_cases"], int)
    assert isinstance(data["firm_remaining_cases"], int)
    assert isinstance(data["optimistic_remaining_cases"], int)


# --- Collection lookup helpers ----------------------------------------------

def find_order_line(order: dict, product_id: str) -> dict:
    for line in order["lines"]:
        if line.get("product_id") == product_id:
            return line
    raise AssertionError(f"order has no line for product {product_id}")


def find_slot(planogram: dict, product_id: str) -> dict:
    for slot in planogram["slots"]:
        if slot.get("product_id") == product_id:
            return slot
    raise AssertionError(f"planogram has no slot for product {product_id}")


def find_projection_entry(location: dict, product_id: str) -> dict:
    for entry in location["on_hand_projection"]:
        if entry.get("product_id") == product_id:
            return entry
    raise AssertionError(f"location projection has no entry for product {product_id}")


def find_claim_line(claim: dict, expiration_date: str) -> dict:
    for line in claim["lines"]:
        if line.get("expiration_date") == expiration_date:
            return line
    raise AssertionError(f"claim has no line with expiration_date {expiration_date}")
