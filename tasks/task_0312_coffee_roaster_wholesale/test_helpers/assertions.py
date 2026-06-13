"""Entity assertions and domain invariant checkers for the Coffee Roaster Wholesale API.

Uses the framework's generic format validators internally. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id / created_at / updated_at / version quartet (every entity except Payment)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_price_tier(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["discount_bps"], int)
    assert 0 <= data["discount_bps"] <= 3000
    assert isinstance(data["min_monthly_kg"], int)
    assert isinstance(data["freshness_max_days"], int)
    assert isinstance(data["archived"], bool)


def assert_account(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["net_terms_days"], int)
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["outstanding_balance_cents"] >= 0
    assert data["status"] in ("ACTIVE", "CREDIT_HOLD")


def assert_roast_profile(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["roast_level"] in ("LIGHT", "MEDIUM", "DARK")
    assert isinstance(data["expected_shrink_bps"], int)
    assert 500 <= data["expected_shrink_bps"] <= 2500


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["base_price_cents_per_kg"], int)
    assert isinstance(data["freshness_window_days"], int)
    assert isinstance(data["archived"], bool)


def assert_green_lot(data: dict):
    _assert_common(data)
    assert isinstance(data["origin"], str) and len(data["origin"]) > 0
    assert isinstance(data["lot_ref"], str) and len(data["lot_ref"]) > 0
    for f in ("on_hand_kg", "reserved_kg", "available_kg", "par_level_kg", "received_kg"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"
    assert_green_lot_invariants(data)


def assert_green_lot_invariants(data: dict):
    """Computed green-inventory invariants that must hold after any operation (PRD §2.7)."""
    assert data["on_hand_kg"] >= 0, "on_hand_kg never negative"
    assert data["reserved_kg"] >= 0, "reserved_kg never negative"
    assert data["available_kg"] >= 0, "available_kg never negative (clamped at zero)"
    assert data["reorder_status"] in ("OK", "BELOW_PAR")


def assert_roast_batch(data: dict):
    _assert_common(data)
    assert data["status"] in ("PLANNED", "ROASTING", "COOLING", "COMPLETED", "CANCELLED")
    assert isinstance(data["planned_green_kg"], (int, float))
    assert isinstance(data["planned_roasted_kg"], (int, float))


def assert_roasted_lot(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("roast_date", "")), "roast_date must be ISO 8601"
    for f in ("produced_kg", "reserved_kg", "on_hand_kg", "available_kg"):
        assert isinstance(data[f], (int, float)), f"{f} must be numeric"
    assert_roasted_lot_invariants(data)


def assert_roasted_lot_invariants(data: dict):
    """Computed roasted-availability invariants (PRD §2.8)."""
    assert data["reserved_kg"] >= 0
    assert data["on_hand_kg"] >= 0
    assert data["available_kg"] >= 0


def assert_standing_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "PAUSED", "CANCELLED")
    assert isinstance(data["cadence_days"], int)
    assert isinstance(data["cycles_released"], int)


def assert_order(data: dict):
    _assert_common(data)
    assert data["fulfillment_status"] in (
        "OPEN", "PARTIALLY_FULFILLED", "FULFILLED", "CANCELLED")
    assert data["billing_status"] in ("UNBILLED", "INVOICED")
    for f in ("subtotal_cents", "discount_cents", "total_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"
    assert data["total_cents"] == data["subtotal_cents"] - data["discount_cents"], \
        "total_cents == subtotal_cents - discount_cents"


def assert_fulfillment(data: dict):
    _assert_common(data)
    assert data["status"] in ("RESERVED", "SHIPPED", "CANCELLED")
    assert isinstance(data["allocated_kg"], (int, float))
    assert is_iso8601_timestamp(data.get("roast_date", "")), "roast_date must be ISO 8601"


def assert_sample_request(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "APPROVED", "DECLINED", "CONVERTED")


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in ("ISSUED", "PARTIALLY_PAID", "PAID", "OVERDUE")
    for f in ("amount_cents", "paid_cents", "amount_due_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"
    assert data["amount_due_cents"] >= 0, "amount_due_cents never negative"
    assert is_iso8601_timestamp(data.get("issued_at", "")), "issued_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("due_at", "")), "due_at must be ISO 8601"


def assert_payment(data: dict):
    """Payment is append-only: id + created_at only, no updated_at / version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] == "CLEARED"


def assert_no_version_fields(data: dict):
    """Append-only event must NOT carry updated_at or version (PRD §2.4)."""
    assert "version" not in data, "Payment must not carry a version field"
    assert "updated_at" not in data, "Payment must not carry an updated_at field"
