"""Entity assertions and domain invariant checkers.

Each assert_<entity> validates structural invariants declared by the PRD:
id/timestamp shapes, enum membership, and — for append-only records — the
absence of updated_at/version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _common_versioned(data: dict):
    _common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int), "version must be an integer"


def assert_customer(data: dict):
    _common_versioned(data)
    assert isinstance(data["email"], str) and data["email"], "email must be non-empty"
    assert isinstance(data["full_name"], str)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert data["tier"] in ("BRONZE", "SILVER", "GOLD")
    assert isinstance(data["loyalty_points_balance"], int)
    assert isinstance(data["lifetime_spend_cents"], int)


def assert_product(data: dict):
    _common_versioned(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["brand"], str)
    assert data["kind"] in ("SINGLE", "BUNDLE", "DISCOVERY_SET")
    assert data["concentration"] in ("EDT", "EDP", "PARFUM", "COLOGNE")
    assert isinstance(data["notes"], list)
    assert isinstance(data["is_exclusive"], bool)
    assert isinstance(data["hygiene_returnable"], bool)


def assert_variant(data: dict):
    _common_versioned(data)
    assert data["kind"] in ("FULL_BOTTLE", "DECANT", "SAMPLE")
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["on_hand_qty"], int) and data["on_hand_qty"] >= 0
    assert isinstance(data["reserved_qty"], int) and data["reserved_qty"] >= 0
    assert data["status"] in ("AVAILABLE", "OUT_OF_STOCK")


def assert_order(data: dict):
    _common_versioned(data)
    assert data["fulfillment_status"] in (
        "CART", "PLACED", "FULFILLED", "CANCELLED", "PARTIALLY_RETURNED", "RETURNED",
    )
    assert data["payment_status"] in ("UNPAID", "PAID", "REFUNDED", "PARTIALLY_REFUNDED")
    for f in ("subtotal_cents", "discount_cents", "loyalty_redeemed_cents",
              "shipping_fee_cents", "total_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"


def assert_order_line(data: dict):
    _common_versioned(data)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["line_total_cents"], int)
    assert isinstance(data["points_earned"], int)
    assert data["status"] in ("ACTIVE", "RETURNED", "CANCELLED")


def assert_subscription(data: dict):
    _common_versioned(data)
    assert data["tier"] in ("BASIC", "PREMIUM")
    assert isinstance(data["monthly_fee_cents"], int)
    assert data["status"] in ("ACTIVE", "PAUSED", "CANCELLED")
    assert isinstance(data["projected_next_charge_cents"], int)


def assert_shipment(data: dict):
    _common_versioned(data)
    assert isinstance(data["charge_cents"], int)
    assert data["status"] in ("PENDING", "FULFILLED")


def assert_allocation_window(data: dict):
    _common_versioned(data)
    assert isinstance(data["total_allocation"], int) and data["total_allocation"] >= 1
    assert isinstance(data["per_customer_cap"], int) and data["per_customer_cap"] >= 1
    assert isinstance(data["claimed_units"], int)
    assert data["status"] in ("SCHEDULED", "OPEN", "CLOSED")


def assert_return_request(data: dict):
    _common_versioned(data)
    assert data["condition"] in ("SEALED", "OPENED")
    assert data["status"] in ("REQUESTED", "APPROVED", "REJECTED")
    assert isinstance(data["refund_estimate_cents"], int)


def assert_allocation_claim(data: dict):
    """Append-only record: id + created_at only, NO updated_at / version."""
    _common(data)
    assert isinstance(data["units"], int) and data["units"] >= 1
    assert "updated_at" not in data, "AllocationClaim is append-only (no updated_at)"
    assert "version" not in data, "AllocationClaim is append-only (no version)"


def assert_loyalty_transaction(data: dict):
    """Append-only record: id + created_at only, NO updated_at / version."""
    _common(data)
    assert isinstance(data["points_delta"], int)
    assert data["reason"] in ("EARN", "REDEEM", "REVERSAL")
    assert data["source_type"] in ("ORDER", "RETURN")
    assert "updated_at" not in data, "LoyaltyTransaction is append-only (no updated_at)"
    assert "version" not in data, "LoyaltyTransaction is append-only (no version)"
