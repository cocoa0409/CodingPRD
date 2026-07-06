"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["store_credit_cents"], int) and data["store_credit_cents"] >= 0
    assert isinstance(data["loyalty_points"], int) and data["loyalty_points"] >= 0
    assert data["loyalty_tier"] in ["STANDARD", "SILVER", "GOLD"]


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["artist"], str)
    assert isinstance(data["title"], str)
    assert data["format"] in ["VINYL", "CD", "CASSETTE"]
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] > 0
    assert isinstance(data["is_rsd_exclusive"], bool)
    assert data["catalog_status"] in [
        "DRAFT", "LISTED", "PRE_ORDER_OPEN", "PRE_ORDER_CLOSED", "DISCONTINUED"
    ]


def assert_allocation(data: dict):
    _assert_common(data)
    assert isinstance(data["allocation_total"], int) and data["allocation_total"] > 0
    assert isinstance(data["available_count"], int) and data["available_count"] >= 0
    assert isinstance(data["reserved_count"], int) and data["reserved_count"] >= 0
    assert isinstance(data["committed_count"], int) and data["committed_count"] >= 0
    assert_allocation_invariants(data)


def assert_allocation_invariants(data: dict):
    """The three pool counters must always sum to allocation_total (PRD §3.5)."""
    total = data["allocation_total"]
    partition = data["available_count"] + data["reserved_count"] + data["committed_count"]
    assert partition == total, (
        f"available+reserved+committed ({partition}) must equal allocation_total ({total})"
    )
    assert data["available_count"] >= 0, "available_count must never go below 0"


def assert_inventory_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["is_used"], bool)
    assert data["condition_grade"] in ["M", "NM", "VG_PLUS", "VG", "G", "F", "P"]
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] > 0
    assert data["status"] in ["AVAILABLE", "ON_DISPLAY", "RESERVED", "SOLD"]


def assert_trade_in(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert data["payout_method"] in ["CREDIT", "CASH"]
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "UNDER_INSPECTION", "APPROVED", "REJECTED", "REVERSED"
    ]
    assert isinstance(data["provisional_value_cents"], int)
    assert isinstance(data["final_value_cents"], int)


def assert_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert data["channel"] in ["ONLINE", "IN_STORE"]
    assert data["payment_status"] in ["UNPAID", "AUTHORIZED", "PAID", "REFUNDED"]
    assert data["fulfillment_status"] in [
        "PENDING", "RESERVED", "SHIPPED", "PICKED_UP", "CANCELLED"
    ]
    for f in ("subtotal_cents", "discount_cents", "shipping_cents", "total_cents", "points_earned"):
        assert isinstance(data[f], int), f"{f} must be int"


def assert_order_totals_consistent(data: dict):
    """total = subtotal - discount + shipping (PRD §3.2 step 5)."""
    expected = data["subtotal_cents"] - data["discount_cents"] + data["shipping_cents"]
    assert data["total_cents"] == expected, (
        f"total_cents ({data['total_cents']}) must equal "
        f"subtotal - discount + shipping ({expected})"
    )


def assert_preorder(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert data["status"] in [
        "RESERVED", "WAITLISTED", "READY_FOR_PICKUP", "FULFILLED", "CANCELLED"
    ]


def assert_consignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["consignor_id"])
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] > 0
    assert data["status"] in ["DRAFT", "ACTIVE", "SOLD", "WITHDRAWN", "EXPIRED"]
    assert isinstance(data["estimated_payout_cents"], int)
    assert isinstance(data["actual_payout_cents"], int)


def assert_grading_dispute(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["inventory_item_id"])
    assert is_valid_uuid(data["customer_id"])
    assert data["status"] in [
        "OPEN", "UNDER_REVIEW", "NEEDS_INFO", "RESOLVED_REGRADE", "RESOLVED_UPHELD", "ESCALATED"
    ]


def assert_special_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0
    assert data["status"] in ["REQUESTED", "SOURCING", "ARRIVED", "FULFILLED", "CANCELLED"]
