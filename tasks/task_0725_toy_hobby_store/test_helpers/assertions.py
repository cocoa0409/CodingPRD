"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_product(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert data["category"] in ["BOARD_GAME", "MODEL_KIT", "PLUSH", "ACTION_FIGURE", "CRAFT_KIT"]
    assert data["status"] in ["DRAFT", "ACTIVE", "DISCONTINUED"]
    assert data["recall_status"] in ["CLEARED", "RECALLED"]
    assert isinstance(data["age_grade_min_months"], int) and data["age_grade_min_months"] >= 0
    assert isinstance(data["msrp_cents"], int) and data["msrp_cents"] >= 0


def assert_inventory_invariants(data: dict):
    """on_hand == available + reserved + quarantined; available >= 0."""
    assert data["available_qty"] >= 0, "available_qty must be non-negative"
    assert data["on_hand_qty"] == data["available_qty"] + data["reserved_qty"] + data["quarantined_qty"], (
        f"inventory conservation violated: on_hand={data['on_hand_qty']} "
        f"available={data['available_qty']} reserved={data['reserved_qty']} "
        f"quarantined={data['quarantined_qty']}"
    )


def assert_allocation_invariants(data: dict):
    """allocated == committed + available_alloc (+ released once RELEASED)."""
    if data["status"] == "RELEASED":
        assert data["allocated_qty"] == data["committed_qty"] + data["available_alloc_qty"] + data["released_qty"]
    else:
        assert data["allocated_qty"] == data["committed_qty"] + data["available_alloc_qty"]


def assert_customer_invariants(data: dict):
    assert data["points_balance"] == data["lifetime_points"] - data["points_redeemed"]
    assert data["lifetime_points"] >= 0
    assert data["points_redeemed"] >= 0
    assert data["points_balance"] >= 0
    assert data["loyalty_tier"] in ["BRONZE", "SILVER", "GOLD"]


def assert_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["fulfillment_status"] in ["OPEN", "SUBMITTED", "READY", "FULFILLED", "CANCELLED"]
    assert data["payment_status"] in ["UNPAID", "PARTIALLY_PAID", "PAID"]
    assert data["pricing_variant"] in ["PROVISIONAL", "FINAL"]


def assert_order_line(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["ACTIVE", "VOIDED", "RETURNED"]
    assert data["extended_cents"] == data["unit_price_cents"] * data["qty"]


def assert_layaway_schedule(data: dict):
    """Schedule sums exactly to total_cents."""
    assert sum(data["installment_schedule_cents"]) == data["total_cents"]
    assert data["remaining_cents"] == data["total_cents"] - data["paid_cents"]
