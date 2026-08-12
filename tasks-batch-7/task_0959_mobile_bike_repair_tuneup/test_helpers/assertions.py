"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_zone(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["base_callout_fee_cents"], int) and data["base_callout_fee_cents"] >= 0
    assert isinstance(data["active"], bool)


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["account_kind"] in ("INDIVIDUAL", "FLEET", "APARTMENT")
    assert isinstance(data["account_credit_cents"], int) and data["account_credit_cents"] >= 0


def assert_bike(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["bike_type"] in ("MECHANICAL", "EBIKE")
    if data["bike_type"] == "EBIKE":
        assert isinstance(data.get("battery_wh"), int), "EBIKE requires battery_wh"
    else:
        assert data.get("battery_wh") is None, "MECHANICAL must carry battery_wh null"
    assert isinstance(data["battery_certified"], bool)
    assert isinstance(data["battery_health_pct"], int) and 0 <= data["battery_health_pct"] <= 100


def assert_mechanic(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["ebike_certified"], bool)
    assert is_valid_uuid(data.get("home_zone_id", ""))
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_van(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["plate"], str) and data["plate"]
    assert is_valid_uuid(data.get("zone_id", ""))
    assert isinstance(data["max_stops_per_day"], int) and data["max_stops_per_day"] >= 1
    assert data["status"] in ("ACTIVE", "OUT_OF_SERVICE")


def assert_part(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["warranty_days"], int) and data["warranty_days"] >= 0
    assert isinstance(data["ebike_only"], bool)


def assert_truck_stock_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("van_id", ""))
    assert is_valid_uuid(data.get("part_id", ""))
    assert isinstance(data["on_hand"], int) and data["on_hand"] >= 0
    assert isinstance(data["reserved"], int)
    assert 0 <= data["reserved"] <= data["on_hand"], "reserved must sit between zero and on_hand"


def assert_stock_movement(data: dict):
    # Append-only event log: id + created_at only; no updated_at / version.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only movement log must not carry updated_at"
    assert "version" not in data, "append-only movement log must not carry version"
    assert is_valid_uuid(data.get("van_id", ""))
    assert is_valid_uuid(data.get("part_id", ""))
    assert isinstance(data["quantity_delta"], int)
    assert data["reason"] in ("RECEIVE", "RETURN_TO_WAREHOUSE", "RESERVE", "RELEASE", "CONSUME")


def assert_service_tier(data: dict):
    _assert_common_fields(data)
    assert data["code"] in ("BASIC", "STANDARD", "PREMIUM")
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert isinstance(data["included_minutes"], int) and data["included_minutes"] >= 1
    assert isinstance(data["overage_rate_cents_per_min"], int) and data["overage_rate_cents_per_min"] >= 0
    assert isinstance(data["labor_warranty_days"], int) and data["labor_warranty_days"] >= 0


def assert_subscription(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["included_tunes_per_period"], int) and data["included_tunes_per_period"] >= 1
    assert 0 < data["discount_pct"] < 1
    assert data["status"] in ("ACTIVE", "PAST_DUE", "SUSPENDED", "CANCELLED")
    assert isinstance(data["allowance_reserved"], int) and data["allowance_reserved"] >= 0
    assert isinstance(data["allowance_consumed"], int) and data["allowance_consumed"] >= 0
    assert_subscription_allowance_invariants(data)


def assert_subscription_allowance_invariants(data: dict):
    """Both allowance readings must reconcile with the raw counters."""
    included = data["included_tunes_per_period"]
    assert data["allowance_remaining"] == included - data["allowance_reserved"] - data["allowance_consumed"]
    assert data["settled_allowance_remaining"] == included - data["allowance_consumed"]


def assert_service_request(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("bike_id", ""))
    assert is_valid_uuid(data.get("zone_id", ""))
    assert is_valid_uuid(data.get("tier_id", ""))
    assert data["request_kind"] in ("STANDARD", "CALLBACK")
    assert data["work_status"] in (
        "QUOTED", "DISPATCHED", "ON_SITE", "IN_SERVICE", "ON_HOLD_PARTS",
        "COMPLETED", "CLOSED", "CANCELLED", "NO_SHOW",
    )
    assert data["billing_status"] in ("ESTIMATED", "INVOICED", "DISPUTED", "PAID")
    assert isinstance(data["quoted_total_cents"], int) and data["quoted_total_cents"] >= 0
    assert isinstance(data["covered_by_subscription"], bool)


def assert_route_day(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("van_id", ""))
    assert isinstance(data["date"], str) and data["date"]
    assert data["status"] in ("OPEN", "LOCKED", "IN_PROGRESS", "CLOSED")
    assert isinstance(data["active_stop_count"], int) and data["active_stop_count"] >= 0


def assert_route_stop(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("route_day_id", ""))
    assert is_valid_uuid(data.get("service_request_id", ""))
    assert isinstance(data["seq"], int) and data["seq"] >= 1
    assert isinstance(data["travel_buffer_minutes"], int) and data["travel_buffer_minutes"] >= 0
    assert data["status"] in ("PLANNED", "ARRIVED", "DONE", "SKIPPED", "UNASSIGNED")


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("service_request_id", ""))
    assert data["status"] in ("DRAFT", "ISSUED", "DISPUTED", "PAID", "VOID")
    assert isinstance(data["is_no_show_fee"], bool)
    assert_invoice_invariants(data)


def assert_invoice_invariants(data: dict):
    """Money lines must reconcile: total = subtotal + surcharge + tax."""
    for field in (
        "callout_cents", "labor_cents", "parts_gross_cents", "discount_cents",
        "subtotal_cents", "surcharge_cents", "tax_cents", "total_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"
    assert data["total_cents"] == data["subtotal_cents"] + data["surcharge_cents"] + data["tax_cents"], (
        f"total {data['total_cents']} != subtotal {data['subtotal_cents']} "
        f"+ surcharge {data['surcharge_cents']} + tax {data['tax_cents']}"
    )
