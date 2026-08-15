"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """Standard system-managed fields present on every resource (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_customer_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["account_number"], str) and data["account_number"]
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["price_tier"] in ("STANDARD", "SILVER", "GOLD", "PLATINUM")
    assert isinstance(data["is_national_account"], bool)
    assert isinstance(data["credit_limit_cents"], int)
    assert data["credit_limit_cents"] >= 0
    assert isinstance(data["approval_threshold_cents"], int)
    assert isinstance(data["primary_ship_to_state"], str)
    assert data["status"] in ("ACTIVE", "CREDIT_HOLD")
    assert isinstance(data["net_spend_cents"], int)
    assert isinstance(data["open_credit_exposure_cents"], int)


def assert_item(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["description"], str)
    assert data["item_class"] in ("STOCKED", "SPECIAL_ORDER", "NON_RETURNABLE")
    assert data["hazmat_restriction"] in ("NONE", "GROUND_ONLY", "WILL_CALL_ONLY")
    assert isinstance(data["restricted_states"], list)
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] > 0
    assert isinstance(data["drop_ship_eligible"], bool)
    assert isinstance(data["vendor_cost_estimate_cents"], int)
    assert isinstance(data["vendor_freight_estimate_cents"], int)


def assert_price_matrix_rule(data: dict):
    _assert_common_fields(data)
    assert data["customer_tier"] in ("STANDARD", "SILVER", "GOLD", "PLATINUM")
    has_item = data.get("item_id") is not None
    has_class = data.get("item_class") is not None
    assert has_item != has_class, "exactly one of item_id / item_class must be set"
    assert data["rule_type"] in ("FIXED_PRICE", "DISCOUNT_PCT")
    assert isinstance(data["effective_from"], str)
    assert isinstance(data["effective_to"], str)
    assert data["status"] in ("DRAFT", "ACTIVE")


def assert_rebate_agreement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["tiers"], list) and len(data["tiers"]) >= 1
    assert data["status"] in ("DRAFT", "ACTIVE", "CLOSED", "SETTLED")
    assert isinstance(data["accrued_spend_cents"], int)
    assert isinstance(data["current_tier_index"], int)
    assert isinstance(data["provisional_rebate_cents"], int)
    # final figures are null until CLOSED; settled credit null until SETTLED
    assert data.get("final_rebate_cents") is None or isinstance(
        data["final_rebate_cents"], int
    )
    assert data.get("true_up_delta_cents") is None or isinstance(
        data["true_up_delta_cents"], int
    )
    assert data.get("settled_credit_cents") is None or isinstance(
        data["settled_credit_cents"], int
    )


def assert_stock_location(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["location_code"], str) and data["location_code"]
    assert data["location_type"] in ("BRANCH", "CENTRAL")
    assert isinstance(data["region_state"], str)
    if data["location_type"] == "BRANCH":
        assert isinstance(data["same_day_cutoff_minute"], int)
        assert 0 <= data["same_day_cutoff_minute"] <= 1439


def assert_stock_balance(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("location_id", ""))
    assert is_valid_uuid(data.get("item_id", ""))
    assert isinstance(data["on_hand_qty"], int)
    assert isinstance(data["reserved_qty"], int)
    assert isinstance(data["available_qty"], int)
    assert_available_qty_identity(data)


def assert_available_qty_identity(balance: dict):
    """available_qty == on_hand_qty - reserved_qty at all times (PRD §2.9)."""
    assert balance["available_qty"] == balance["on_hand_qty"] - balance["reserved_qty"], (
        f"available_qty identity violated: {balance['available_qty']} != "
        f"{balance['on_hand_qty']} - {balance['reserved_qty']}"
    )


def assert_requisition_cart(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    for line in data["lines"]:
        assert is_valid_uuid(line.get("item_id", ""))
        assert isinstance(line["qty"], int) and line["qty"] >= 1
    assert isinstance(data["estimated_total_cents"], int)
    assert data["status"] in (
        "OPEN", "PENDING_APPROVAL", "APPROVED", "REJECTED", "CONVERTED",
    )
    if data["status"] == "REJECTED":
        assert isinstance(data.get("rejection_reason"), str)


def assert_sales_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("fulfillment_branch_id", ""))
    assert data["fulfillment_method"] in ("WILL_CALL", "SAME_DAY", "STANDARD")
    assert data["status"] in ("SUBMITTED", "CONFIRMED", "COMPLETED", "CANCELLED")
    assert data["fulfillment_status"] in (
        "UNALLOCATED", "ALLOCATED", "PARTIALLY_ALLOCATED",
        "READY_FOR_WILL_CALL", "SHIPPED", "FULFILLED",
    )
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["freight_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert data["total_cents"] == data["subtotal_cents"] + data["freight_cents"]
    assert isinstance(data["sla_breach"], bool)


def assert_order_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("item_id", ""))
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["line_total_cents"], int)
    assert data["line_total_cents"] == data["qty"] * data["unit_price_cents"]
    for field in ("qty_branch", "qty_central", "qty_drop_ship", "qty_backordered"):
        assert isinstance(data[field], int) and data[field] >= 0
    assert data["fulfillment_source"] in (
        "UNRESOLVED", "BRANCH_ONLY", "SPLIT_STOCK", "DROP_SHIP_ONLY",
        "BACKORDER_ONLY", "MIXED",
    )
    assert isinstance(data["qty_vendor_confirmed"], int)
    assert data["margin_status"] in ("NOT_APPLICABLE", "PROVISIONAL", "FINALIZED")


def assert_return_authorization(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("order_id", ""))
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    for line in data["lines"]:
        assert is_valid_uuid(line.get("order_line_id", ""))
        assert isinstance(line["qty"], int) and line["qty"] >= 1
        assert line["condition"] in ("RESALEABLE", "DAMAGED")
    assert data["status"] in (
        "REQUESTED", "APPROVED", "REJECTED", "RECEIVED", "CREDITED",
    )
    assert data.get("credit_cents") is None or isinstance(data["credit_cents"], int)
    assert data.get("restocking_fee_cents") is None or isinstance(
        data["restocking_fee_cents"], int
    )
