"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id/created_at/updated_at/version on a versioned aggregate."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1, "version must be a positive int"


def _assert_ledger(data: dict):
    """Append-only ledger records carry only id + created_at (no version/updated_at)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only record must not carry version"
    assert "updated_at" not in data, "append-only record must not carry updated_at"


def assert_nursery(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert 1 <= data["site_hardiness_zone"] <= 13


def assert_account(data: dict):
    _assert_common(data)
    assert data["account_type"] in ["RETAIL", "LANDSCAPER_B2B"]
    assert data["status"] in ["ACTIVE", "CREDIT_HOLD"]
    assert data["loyalty_tier"] in ["STANDARD", "GOLD"]
    assert 1 <= data["ship_to_hardiness_zone"] <= 13
    assert data["credit_limit_cents"] >= 0
    assert data["outstanding_balance_cents"] >= 0
    assert data["lifetime_points"] >= 0
    assert data["points_balance"] >= 0


def assert_product(data: dict):
    _assert_common(data)
    assert data["category"] in ["LIVE_PLANT", "BULK_MATERIAL", "DRY_GOOD"]
    assert data["unit"] in ["EACH", "CUBIC_YARD"]
    assert data["lifecycle_class"] in ["ANNUAL", "PERENNIAL", "NONE"]
    assert data["unit_price_cents"] >= 0
    assert 0 <= data["warranty_pct"] <= 100


def assert_inventory_lot(data: dict):
    _assert_common(data)
    assert data["status"] in ["QUARANTINE", "AVAILABLE", "DEPLETED"]
    assert data["received_qty"] > 0
    assert data["unit_cost_cents"] >= 0
    assert data["qty_on_hand"] >= 0
    assert data["reserved_qty"] >= 0
    assert data["shrink_qty"] >= 0
    assert data["sold_qty"] >= 0


def assert_care_log_entry(data: dict):
    _assert_ledger(data)
    assert data["entry_type"] in ["WATERING", "TREATMENT", "INSPECTION", "SHRINK_LOSS"]
    assert data["qty_lost"] >= 0


def assert_promotion(data: dict):
    _assert_common(data)
    assert data["category_scope"] in ["LIVE_PLANT", "BULK_MATERIAL", "DRY_GOOD", "ALL"]
    assert 0 <= data["discount_pct"] <= 60
    assert data["status"] in ["SCHEDULED", "ACTIVE", "ENDED"]


def assert_vehicle(data: dict):
    _assert_common(data)
    assert data["vehicle_type"] in ["FLATBED", "BOX_TRUCK"]
    assert data["capacity_cubic_yards"] > 0
    assert data["turnaround_minutes"] >= 0


def assert_order(data: dict):
    _assert_common(data)
    assert data["fulfillment_status"] in ["DRAFT", "CONFIRMED", "ALLOCATED", "FULFILLED", "CANCELLED"]
    assert data["payment_status"] in ["UNPAID", "ON_ACCOUNT", "PAID"]
    assert data["gross_total_cents"] >= 0
    assert data["promo_discount_cents"] >= 0
    assert data["redemption_cents"] >= 0
    assert data["net_total_cents"] >= 0


def assert_order_line(data: dict):
    _assert_common(data)
    assert data["status"] in ["PENDING", "ALLOCATED", "FULFILLED", "RELEASED"]
    assert data["qty"] > 0
    assert data["unit_price_cents"] >= 0
    assert data["line_discount_cents"] >= 0


def assert_special_order(data: dict):
    _assert_common(data)
    assert data["status"] in ["REQUESTED", "APPROVED", "RECEIVED", "CANCELLED"]
    assert data["requested_qty"] > 0
    assert data["quoted_unit_cost_cents"] >= 0
    assert data["deposit_cents"] >= 0


def assert_delivery(data: dict):
    _assert_common(data)
    assert data["status"] in ["SCHEDULED", "DISPATCHED", "DELIVERED", "CANCELLED"]
    assert data["bulk_volume_cubic_yards"] >= 0


def assert_warranty_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ["FILED", "APPROVED", "DENIED"]
    assert data["resolution"] in ["REPLACEMENT", "REFUND"]
    assert data["claim_qty"] > 0
    assert data["payout_cents"] >= 0


def assert_loyalty_event(data: dict):
    _assert_ledger(data)
    assert data["event_type"] in ["ACCRUAL", "REDEMPTION", "REVERSAL"]
    assert data["source_kind"] in ["ORDER", "WARRANTY_CLAIM"]


def assert_lot_unit_conservation(lot: dict):
    """Physical-unit invariant: received == on_hand + reserved + shrink + sold."""
    total = (
        lot["qty_on_hand"]
        + lot["reserved_qty"]
        + lot["shrink_qty"]
        + lot["sold_qty"]
    )
    assert lot["received_qty"] == total, (
        f"lot unit conservation violated: received {lot['received_qty']} != "
        f"on_hand {lot['qty_on_hand']} + reserved {lot['reserved_qty']} + "
        f"shrink {lot['shrink_qty']} + sold {lot['sold_qty']}"
    )
