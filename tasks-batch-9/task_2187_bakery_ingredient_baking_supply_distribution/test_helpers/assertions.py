"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

ALLERGEN_CLASSES = ["NONE", "GLUTEN", "TREE_NUT", "PEANUT", "DAIRY", "EGG", "SOY"]
ALLERGEN_PROGRAMS = ["STANDARD", "GLUTEN_FREE_CERTIFIED", "NUT_FREE_CERTIFIED"]


def assert_common_fields(data: dict):
    """PRD §2.4: an `id` that is a server-minted UUID with no type prefix, a
    `created_at` timestamp, an `updated_at` timestamp and an integer `version`
    that starts at 1 on creation."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be >= 1"


def assert_append_only_fields(data: dict):
    """PRD §2.4: a `CommodityIndexQuote` carries only `id` and `created_at`."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"


def assert_customer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and 1 <= len(data["legal_name"]) <= 120
    assert data["allergen_program"] in ALLERGEN_PROGRAMS
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert isinstance(data["min_drop_cents"], int)
    assert data["status"] in ["ACTIVE", "CREDIT_HOLD"]
    assert isinstance(data["open_exposure_cents"], int)
    assert float(data["allergen_risk_score"]) >= 0.0
    assert float(data["allergen_risk_score"]) <= 100.0
    assert data["risk_tier"] in ["GREEN", "AMBER", "RED"]


def assert_product(data: dict):
    assert_common_fields(data)
    assert isinstance(data["sku"], str) and 3 <= len(data["sku"]) <= 32
    assert data["category"] in ["FLOUR", "LEAVENING", "FAT", "INCLUSION", "PACKAGING"]
    assert data["allergen_class"] in ALLERGEN_CLASSES
    assert isinstance(data["bulk_capable"], bool)
    assert isinstance(data["shelf_life_days"], int) and data["shelf_life_days"] >= 1
    assert data["index_code"] in ["NONE", "HRW_WHEAT", "SRW_WHEAT", "SOFT_OIL", "CANE_SUGAR"]
    assert isinstance(data["list_price_cents_per_lb"], int) and data["list_price_cents_per_lb"] >= 1
    assert isinstance(data["min_rotation_days"], int) and data["min_rotation_days"] >= 0


def assert_index_quote(data: dict):
    assert_append_only_fields(data)
    assert data["index_code"] in ["HRW_WHEAT", "SRW_WHEAT", "SOFT_OIL", "CANE_SUGAR"]
    assert isinstance(data["price_cents_per_lb"], int) and data["price_cents_per_lb"] >= 1


def assert_warehouse_zone(data: dict):
    assert_common_fields(data)
    assert isinstance(data["zone_code"], str) and 2 <= len(data["zone_code"]) <= 16
    assert data["allergen_class"] in ALLERGEN_CLASSES
    assert data["status"] in ["OPEN", "SANITATION_LOCKOUT"]
    assert float(data["on_hand_lb"]) >= 0


def assert_forward_contract(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert data["pricing_mode"] in ["ORDER_DATE_INDEX", "DELIVERY_DATE_INDEX"]
    assert data["status"] in [
        "DRAFT", "OFFERED", "COUNTERED", "ACTIVE", "EXHAUSTED", "TERMINATED", "EXPIRED",
    ]
    assert isinstance(data["negotiation_round"], int) and 0 <= data["negotiation_round"] <= 3
    assert float(data["committed_volume_lb"]) >= 0
    assert float(data["drawn_volume_lb"]) >= 0


def assert_contract_line(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["contract_id"])
    assert is_valid_uuid(data["product_id"])
    assert float(data["volume_committed_lb"]) >= 1000
    assert -500 <= int(data["basis_cents_per_lb"]) <= 500
    assert float(data["volume_drawn_lb"]) >= 0


def assert_lot(data: dict):
    assert_common_fields(data)
    assert isinstance(data["lot_code"], str) and 4 <= len(data["lot_code"]) <= 32
    assert is_valid_uuid(data["product_id"])
    assert is_valid_uuid(data["zone_id"])
    assert data["status"] in ["AVAILABLE", "QUARANTINED", "DISPOSED", "EXPIRED", "DEPLETED"]
    assert_lot_inventory_conservation(data)


def assert_lot_inventory_conservation(data: dict):
    """PRD §2.9: "For every lot, the sum of `quantity_on_hand_lb`,
    `quantity_reserved_lb` and `quantity_consumed_lb` equals
    `quantity_received_lb`, exactly, at two decimal places."
    """
    total = (
        round(float(data["quantity_on_hand_lb"]), 2)
        + round(float(data["quantity_reserved_lb"]), 2)
        + round(float(data["quantity_consumed_lb"]), 2)
    )
    assert round(total, 2) == round(float(data["quantity_received_lb"]), 2), (
        "lot inventory conservation broken: "
        f"{data['quantity_on_hand_lb']} + {data['quantity_reserved_lb']} + "
        f"{data['quantity_consumed_lb']} != {data['quantity_received_lb']}"
    )


def assert_silo(data: dict):
    assert_common_fields(data)
    assert isinstance(data["silo_code"], str) and 2 <= len(data["silo_code"]) <= 16
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["product_id"])
    assert float(data["capacity_lb"]) >= 1000
    assert 0 <= float(data["residual_lb"]) <= float(data["capacity_lb"])


def assert_order(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert data["delivery_mode"] in ["BULK", "BAGGED"]
    assert data["fulfillment_status"] in [
        "NEW", "ALLOCATED", "ROUTED", "LOADED", "DELIVERED", "SHORT_SHIPPED", "CANCELLED",
    ]
    assert data["pricing_status"] in ["UNPRICED", "PROVISIONAL", "FINAL", "INVOICED", "VOID"]
    assert isinstance(data["surge_window"], bool)
    for field in (
        "subtotal_cents",
        "fuel_surcharge_cents",
        "tech_attach_fee_cents",
        "volume_rebate_cents",
        "total_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_order_settlement_total(data: dict):
    """PRD §3.4: "`total_cents` is the subtotal plus the fuel surcharge plus the
    formulation-support attach fee, less the volume rebate."
    """
    expected = (
        data["subtotal_cents"]
        + data["fuel_surcharge_cents"]
        + data["tech_attach_fee_cents"]
        - data["volume_rebate_cents"]
    )
    assert data["total_cents"] == expected, (
        f"total_cents {data['total_cents']} != subtotal {data['subtotal_cents']} "
        f"+ fuel {data['fuel_surcharge_cents']} + attach {data['tech_attach_fee_cents']} "
        f"- rebate {data['volume_rebate_cents']}"
    )


def assert_order_line(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["product_id"])
    assert float(data["quantity_lb"]) > 0
    assert data["allocation_status"] in ["UNALLOCATED", "RESERVED", "RELEASED", "SHIPPED"]
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["extended_cents"], int)


def assert_substitution_request(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["order_line_id"])
    assert is_valid_uuid(data["proposed_product_id"])
    assert data["status"] in [
        "REQUESTED", "UNDER_REVIEW", "REVISION_REQUESTED", "APPROVED", "REJECTED", "WITHDRAWN",
    ]
    assert isinstance(data["revision_round"], int) and 0 <= data["revision_round"] <= 2
    assert isinstance(data["requested_by_user_id"], str) and data["requested_by_user_id"]


def assert_route(data: dict):
    assert_common_fields(data)
    assert isinstance(data["route_code"], str) and 2 <= len(data["route_code"]) <= 16
    assert float(data["vehicle_capacity_lb"]) >= 1000
    assert int(data["service_buffer_minutes"]) >= 0
    assert data["status"] in ["PLANNING", "SEALED", "DISPATCHED", "COMPLETED", "ABORTED"]
    assert data["allergen_class_lock"] in ALLERGEN_CLASSES
    assert float(data["planned_load_lb"]) >= 0
    assert int(data["stop_count"]) >= 0


def assert_route_utilization(data: dict):
    """PRD §3.9: "`utilization_pct` is the planned load divided by the vehicle
    capacity, multiplied by one hundred, and rounded half-up to two decimal
    places."
    """
    capacity = float(data["vehicle_capacity_lb"])
    expected = round(float(data["planned_load_lb"]) / capacity * 100 + 1e-9, 2)
    assert abs(float(data["utilization_pct"]) - expected) < 0.005, (
        f"utilization_pct {data['utilization_pct']} != expected {expected}"
    )


def assert_route_stop(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["route_id"])
    assert is_valid_uuid(data["order_id"])
    assert data["status"] in ["PLANNED", "DELIVERED", "SHORTED", "CANCELLED"]
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 0


def assert_tech_engagement(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data["customer_id"])
    assert is_valid_uuid(data["product_id"])
    assert data["status"] in ["OPEN", "BILLABLE", "ATTACHED", "WAIVED"]
    assert float(data["hours_logged"]) >= 0
    assert isinstance(data["attach_fee_cents"], int) and data["attach_fee_cents"] >= 0
    assert isinstance(data["assigned_specialist_user_id"], str)


def assert_risk_tier_matches_score(data: dict):
    """PRD §3.7: "`risk_tier` is then re-derived: `GREEN` below 25.00, `AMBER`
    from 25.00 up to but not including 60.00, and `RED` at 60.00 and above."
    """
    score = float(data["allergen_risk_score"])
    if score < 25.00:
        expected = "GREEN"
    elif score < 60.00:
        expected = "AMBER"
    else:
        expected = "RED"
    assert data["risk_tier"] == expected, (
        f"risk_tier {data['risk_tier']} does not match score {score} (expected {expected})"
    )
