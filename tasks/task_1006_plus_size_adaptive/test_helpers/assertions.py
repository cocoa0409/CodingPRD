"""Entity assertions and domain invariant checkers.

Field names are PRD-exact. Assertions cover the shape a faithful implementation
must return; they never demand fields the PRD tells the implementer to omit
(e.g. OrderLine has no updated_at / version).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["size_code"], int)
    assert isinstance(data["adaptive_needs"], list)
    assert data["loyalty_tier"] in ("STANDARD", "INSIDER", "VIP")
    assert data["account_status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert data["booking_status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["loyalty_points_balance"], int)
    assert isinstance(data["loyalty_lifetime_points"], int)
    assert isinstance(data["wallet_credit_cents"], int)
    assert isinstance(data["no_show_count"], int)


def assert_product(data: dict):
    _assert_common(data)
    assert data["category"] in ("TOPS", "BOTTOMS", "DRESSES", "OUTERWEAR", "INTIMATES")
    assert isinstance(data["base_price_cents"], int)
    assert isinstance(data["size_min"], int)
    assert isinstance(data["size_max"], int)
    assert data["size_min"] <= data["size_max"]
    assert isinstance(data["adaptive_features"], list)


def assert_variant(data: dict):
    _assert_common(data)
    assert isinstance(data["size_code"], int)
    assert isinstance(data["inventory_on_hand"], int)
    assert isinstance(data["inventory_reserved"], int)
    assert isinstance(data["inventory_available"], int)
    assert_inventory_ledger(data)


def assert_inventory_ledger(data: dict):
    """inventory_available is always on_hand minus reserved, and never negative."""
    assert data["inventory_available"] == data["inventory_on_hand"] - data["inventory_reserved"], (
        "inventory_available must equal inventory_on_hand - inventory_reserved: "
        f"{data['inventory_available']} != {data['inventory_on_hand']} - {data['inventory_reserved']}"
    )
    assert data["inventory_reserved"] >= 0, "inventory_reserved must not go negative"


def assert_order_line(data: dict):
    assert is_valid_uuid(data.get("id", "")), "order line id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    # OrderLine is an immutable snapshot: no updated_at / version.
    assert "updated_at" not in data, "OrderLine must not carry updated_at"
    assert "version" not in data, "OrderLine must not carry version"
    assert data["line_total_cents"] == data["unit_price_cents"] * data["quantity"], (
        "line_total_cents must equal unit_price_cents * quantity"
    )


def assert_order(data: dict):
    _assert_common(data)
    assert data["payment_status"] in ("PENDING", "AUTHORIZED", "CAPTURED", "REFUNDED")
    assert data["fulfillment_status"] in (
        "UNFULFILLED", "PICKING", "SHIPPED", "DELIVERED", "CANCELLED",
    )
    assert isinstance(data["total_cents"], int)


def assert_appointment(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "REQUESTED", "CONFIRMED", "RESCHEDULE_REQUESTED", "COMPLETED", "CANCELLED", "NO_SHOW",
    )
    assert data["topic"] in ("GENERAL", "ADAPTIVE", "PLUS_FORMAL", "MATERNITY")
    assert isinstance(data["late_cancel_fee_cents"], int)


def assert_return(data: dict):
    _assert_common(data)
    assert data["return_type"] in ("RETURN", "EXCHANGE")
    assert data["status"] in ("REQUESTED", "APPROVED", "INSPECTED", "COMPLETED", "REJECTED")
    assert isinstance(data["line_ids"], list)


def assert_subscription(data: dict):
    _assert_common(data)
    assert data["plan_tier"] in ("ESSENTIALS", "SIGNATURE", "LUXE")
    assert data["status"] in ("ACTIVE", "PAUSED", "CANCELLED")
    assert isinstance(data["styling_fee_cents"], int)
    assert isinstance(data["version"], int)


def assert_shipment(data: dict):
    _assert_common(data)
    assert data["status"] in ("CURATED", "SHIPPED", "KEPT_PENDING", "SETTLED")
    assert isinstance(data["items"], list)
