"""Entity assertions and domain invariant checkers.

Each assert_* validates the response shape implied by the PRD resource
narratives (sections 2.4, 2.9 and the section 3 workflows).
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be int"


def assert_merch_program(data: dict):
    _assert_common(data, "MerchProgram")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["school_year"], str) and data["school_year"]
    assert data["status"] in ["SETUP", "ACTIVE", "CLOSED", "RECONCILED"]
    assert isinstance(data["over_short_tolerance_cents"], int)
    assert isinstance(data["exchange_window_days"], int)
    assert isinstance(data["pickup_window_days"], int)
    assert isinstance(data["register_buffer_minutes"], int)
    assert isinstance(data["deposit_floor_cents"], int)
    assert data["valuation_method"] in ["FIFO", "WEIGHTED_AVG"]
    assert isinstance(data["undistributed_profit_cents"], int)
    assert isinstance(data["distributed_profit_cents"], int)
    assert isinstance(data["ops_run_index"], int)


def assert_vendor(data: dict):
    _assert_common(data, "Vendor")
    assert isinstance(data["program_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["contact_email"], str)
    assert data["status"] in ["PENDING", "APPROVED", "SUSPENDED"]
    assert isinstance(data["quotes"], list)


def assert_design(data: dict):
    _assert_common(data, "Design")
    assert isinstance(data["program_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["artwork_ref"], str)
    assert isinstance(data["royalty_pct"], (int, float))
    assert 0 <= data["royalty_pct"] <= 1
    assert isinstance(data["licensing_fee_cents"], int)
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "REVOKED"]
    assert isinstance(data["revision_count"], int)


def assert_product_variant(data: dict):
    _assert_common(data, "ProductVariant")
    assert isinstance(data["program_id"], str)
    assert isinstance(data["design_id"], str)
    assert data["size"] in ["XS", "S", "M", "L", "XL", "2XL", "ONE_SIZE"]
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["on_hand_qty"], int)
    assert isinstance(data["reserved_online_qty"], int)
    assert isinstance(data["available_qty"], int)
    assert data["available_qty"] == data["on_hand_qty"] - data["reserved_online_qty"]
    assert data["available_qty"] >= 0
    assert isinstance(data["landed_unit_cost_cents"], int)


def assert_seasonal_drop(data: dict):
    _assert_common(data, "SeasonalDrop")
    assert isinstance(data["program_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert is_iso8601_timestamp(data["opens_at"])
    assert is_iso8601_timestamp(data["closes_at"])
    assert data["status"] in ["SCHEDULED", "OPEN", "CLOSED", "SETTLED"]


def assert_purchase_order(data: dict):
    _assert_common(data, "PurchaseOrder")
    assert isinstance(data["program_id"], str)
    assert isinstance(data["variant_id"], str)
    assert isinstance(data["vendor_id"], str)
    assert isinstance(data["qty_ordered"], int) and data["qty_ordered"] >= 1
    assert isinstance(data["qty_received"], int) and data["qty_received"] >= 0
    assert data["qty_received"] <= data["qty_ordered"]
    assert isinstance(data["unit_cost_cents"], int)
    assert isinstance(data["auto_created"], bool)
    assert data["status"] in [
        "DRAFT",
        "SUBMITTED",
        "PARTIALLY_RECEIVED",
        "RECEIVED",
        "CANCELLED",
    ]


def assert_preorder_campaign(data: dict):
    _assert_common(data, "PreOrderCampaign")
    assert isinstance(data["program_id"], str)
    assert isinstance(data["design_id"], str)
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["deposit_pct"], (int, float))
    assert 0 <= data["deposit_pct"] <= 1
    assert isinstance(data["goal_units"], int)
    assert data["status"] in [
        "DRAFT",
        "OPEN",
        "IN_PRODUCTION",
        "FULFILLING",
        "CLOSED",
        "CANCELLED",
    ]
    assert isinstance(data["placed_units"], int)
    assert isinstance(data["paid_units"], int)
    assert data["paid_units"] <= data["placed_units"]


def assert_preorder(data: dict):
    _assert_common(data, "PreOrder")
    assert isinstance(data["program_id"], str)
    assert isinstance(data["campaign_id"], str)
    assert isinstance(data["variant_id"], str)
    assert isinstance(data["customer_user_id"], str)
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert data["status"] in ["PLACED", "PAID", "FULFILLED", "CANCELLED", "REFUNDED"]
    assert isinstance(data["deposit_due_cents"], int)
    assert isinstance(data["balance_due_cents"], int)
    assert isinstance(data["deposit_paid_cents"], int)
    assert isinstance(data["balance_paid_cents"], int)
    assert isinstance(data["refunded_cents"], int)


def assert_event_sale(data: dict):
    _assert_common(data, "EventSale")
    assert isinstance(data["program_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["register_location"], str)
    assert data["status"] in [
        "SCHEDULED",
        "OPEN",
        "COUNTED",
        "FLAGGED",
        "RECONCILED",
        "CANCELLED",
    ]
    assert isinstance(data["cash_sales_cents"], int)
    assert isinstance(data["card_sales_cents"], int)
    assert isinstance(data["cash_refunds_cents"], int)


def assert_order(data: dict):
    _assert_common(data, "Order")
    assert isinstance(data["program_id"], str)
    assert data["channel"] in ["EVENT_POS", "ONLINE"]
    assert isinstance(data["customer_user_id"], str)
    assert data["payment_method"] in ["CASH", "CARD"]
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["margin_cents"], int)
    assert data["payment_status"] in ["PAID", "PARTIALLY_REFUNDED", "REFUNDED"]
    assert data["fulfillment_status"] in [
        "POS_FULFILLED",
        "PICKUP_PENDING",
        "READY_FOR_PICKUP",
        "PICKED_UP",
        "EXPIRED_RELEASED",
    ]
    assert isinstance(data["refunded_cents"], int)
    assert data["refunded_cents"] <= data["total_cents"]


def assert_exchange_request(data: dict):
    _assert_common(data, "ExchangeRequest")
    assert isinstance(data["program_id"], str)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["original_variant_id"], str)
    assert isinstance(data["new_variant_id"], str)
    assert data["status"] in ["PENDING", "APPROVED", "COMPLETED", "REJECTED"]
    assert isinstance(data["differential_cents"], int)


def assert_activity_account(data: dict):
    _assert_common(data, "ActivityAccount")
    assert isinstance(data["program_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["allocation_weight"], (int, float))
    assert data["allocation_weight"] > 0
    assert isinstance(data["balance_cents"], int)


def assert_allocation_run(data: dict):
    _assert_common(data, "AllocationRun")
    assert isinstance(data["program_id"], str)
    assert isinstance(data["distributable_cents"], int)
    assert data["distributable_cents"] >= 1
    assert data["status"] in ["DRAFT", "POSTED", "REVERSED"]
    assert isinstance(data["lines"], list)
    for line in data["lines"]:
        assert isinstance(line["account_id"], str)
        assert isinstance(line["credit_cents"], int)
        assert isinstance(line["capped"], bool)


def assert_profit_split_invariants(program: dict):
    """Domain invariant on the program profit split (PRD section 3.8)."""
    assert program["undistributed_profit_cents"] >= 0
    assert program["distributed_profit_cents"] >= 0
    assert isinstance(program["undistributed_profit_cents"], int)
    assert isinstance(program["distributed_profit_cents"], int)
