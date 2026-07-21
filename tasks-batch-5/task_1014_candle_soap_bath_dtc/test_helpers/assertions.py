"""Entity assertions and domain invariant checkers (PRD §2.4, §2.6)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_product(data: dict):
    _assert_common(data)
    assert data["product_type"] in ("CANDLE", "WAX_MELT", "SOAP", "BATH_BOMB")
    assert isinstance(data["collection_name"], str)
    assert isinstance(data["scent_family"], str)
    assert isinstance(data["title"], str)


def assert_sku(data: dict):
    _assert_common(data)
    assert data["size"] in ("SMALL", "MEDIUM", "LARGE")
    assert isinstance(data["scent"], str)
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] > 0
    assert isinstance(data["requires_safety_label"], bool)


def assert_batch(data: dict):
    _assert_common(data)
    assert data["status"] in ("CREATED", "LABELED", "RELEASED", "DEPLETED", "RECALLED")
    assert isinstance(data["is_safety_labeled"], bool)
    assert_batch_invariant(data)


def assert_batch_invariant(data: dict):
    """PRD §2.6: produced == available + reserved + shipped + recalled; available >= 0."""
    produced = data["quantity_produced"]
    available = data["quantity_available"]
    reserved = data["quantity_reserved"]
    shipped = data["quantity_shipped"]
    recalled = data["quantity_recalled"]
    assert available >= 0, "quantity_available must never be negative"
    assert produced == available + reserved + shipped + recalled, (
        f"availability invariant violated: produced={produced} != "
        f"available={available} + reserved={reserved} + shipped={shipped} + recalled={recalled}"
    )


def assert_customer(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["loyalty_points_balance"], int)
    assert data["loyalty_tier"] in ("BRONZE", "SILVER", "GOLD")


def assert_order(data: dict):
    _assert_common(data)
    assert data["payment_status"] in ("UNPAID", "PAID", "REFUNDED")
    assert data["fulfillment_status"] in (
        "PENDING", "ALLOCATED", "DELIVERED", "CANCELLED", "RETURNED",
    )
    assert data["order_type"] in ("RETAIL", "BULK", "GIFT")


def assert_order_line(data: dict):
    _assert_common(data)
    assert data["status"] in ("RESERVED", "SHIPPED", "RELEASED", "VOIDED_RECALL", "RETURNED")


def assert_return(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "APPROVED", "REJECTED", "REFUNDED")


def assert_subscription(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "PAUSED", "CANCELLED")


def assert_loyalty_tier_for_balance(balance: int, tier: str):
    """PRD §3.5: BRONZE < 500 <= SILVER < 2000 <= GOLD."""
    if balance < 500:
        expected = "BRONZE"
    elif balance < 2000:
        expected = "SILVER"
    else:
        expected = "GOLD"
    assert tier == expected, f"balance {balance} should map to {expected}, got {tier}"
