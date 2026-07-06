"""Entity assertions and domain invariant checkers.

Each assert_{entity}() checks identity/timestamp shape and that every declared field
carries a value of the correct type. Invariant checkers verify PRD-level conservation
guarantees (§2.6 availability conservation).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_MARKET_CYCLE_STATES = {"SCHEDULED", "OPEN", "CUTOFF", "SETTLED"}
_ORDER_STATES = {"CART", "PLACED", "ALLOCATED", "FULFILLED", "CANCELLED"}
_PAYMENT_STATES = {"UNPAID", "AUTHORIZED", "CAPTURED", "PARTIALLY_REFUNDED", "REFUNDED"}
_LINE_STATES = {"REQUESTED", "ALLOCATED", "PACKED", "SUBSTITUTED", "SHORTED", "FULFILLED", "CANCELLED"}
_SUB_STATES = {"ACTIVE", "PAUSED", "CANCELLED"}


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_farm(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert 0 <= data["commission_pct"] <= 1, "commission_pct must be within [0, 1]"
    assert isinstance(data["snap_authorized"], bool)
    assert isinstance(data["payout_balance_cents"], int)
    assert isinstance(data["settled_cycle_count"], int) and data["settled_cycle_count"] >= 0


def assert_product(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("farm_id", "")), "farm_id must be a UUID"
    assert data["category"] in {"PRODUCE", "DAIRY", "MEAT", "PANTRY", "OTHER"}
    assert data["pricing_mode"] in {"FIXED", "WEIGHT"}
    assert isinstance(data["snap_eligible"], bool)


def assert_market_cycle(data: dict):
    _assert_common(data)
    assert data["status"] in _MARKET_CYCLE_STATES, f"unexpected cycle status {data['status']}"
    assert isinstance(data["region_code"], str) and data["region_code"]


def assert_offering(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be a UUID"
    assert is_valid_uuid(data.get("market_cycle_id", "")), "market_cycle_id must be a UUID"
    assert isinstance(data["offered_qty"], int) and data["offered_qty"] >= 1
    assert isinstance(data["reserved_qty"], int) and data["reserved_qty"] >= 0
    assert isinstance(data["committed_qty"], int) and data["committed_qty"] >= 0
    assert isinstance(data["remaining_qty"], int) and data["remaining_qty"] >= 0
    assert_offering_conservation(data)


def assert_offering_conservation(offering: dict):
    """PRD §2.6: offered_qty always equals remaining_qty + reserved_qty + committed_qty,
    and remaining_qty is never negative."""
    assert offering["remaining_qty"] >= 0, "remaining_qty must never be negative"
    total = offering["remaining_qty"] + offering["reserved_qty"] + offering["committed_qty"]
    assert offering["offered_qty"] == total, (
        f"conservation broken: offered_qty {offering['offered_qty']} != "
        f"remaining {offering['remaining_qty']} + reserved {offering['reserved_qty']} "
        f"+ committed {offering['committed_qty']}"
    )


def assert_pickup_hub(data: dict):
    _assert_common(data)
    assert data["hub_type"] in {"PICKUP", "DELIVERY"}
    assert isinstance(data["slot_capacity"], int) and data["slot_capacity"] >= 1


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["snap_balance_cents"], int) and data["snap_balance_cents"] >= 0
    assert isinstance(data["wallet_credit_cents"], int) and data["wallet_credit_cents"] >= 0
    assert isinstance(data["doubleup_used_cents"], int) and data["doubleup_used_cents"] >= 0


def assert_subscription(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a UUID"
    assert data["status"] in _SUB_STATES
    assert data["box_size"] in {"SMALL", "MEDIUM", "LARGE"}
    assert data["cadence"] in {"WEEKLY", "BIWEEKLY"}


def assert_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a UUID"
    assert data["order_status"] in _ORDER_STATES
    assert data["payment_status"] in _PAYMENT_STATES
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["customer_owed_cents"], int)
    assert data["customer_owed_cents"] >= 0, "customer_owed_cents is never negative"


def assert_order_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert is_valid_uuid(data.get("offering_id", "")), "offering_id must be a UUID"
    assert isinstance(data["requested_qty"], int) and data["requested_qty"] >= 1
    assert data["line_status"] in _LINE_STATES
    assert isinstance(data["snap_eligible"], bool)


def assert_settlement(data: dict):
    """PRD §2.4: a settlement carries only id + created_at (no updated_at / version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "settlement is immutable and has no updated_at"
    assert "version" not in data, "settlement is immutable and has no version"
    assert isinstance(data["gross_sales_cents"], int)
    assert isinstance(data["commission_cents"], int)
    assert isinstance(data["net_payout_cents"], int)
    assert isinstance(data["line_count"], int) and data["line_count"] >= 0
    assert data["net_payout_cents"] == data["gross_sales_cents"] - data["commission_cents"], (
        "net_payout_cents must equal gross_sales_cents - commission_cents"
    )
