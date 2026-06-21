"""Entity assertions and domain invariant checkers.

These validate shape and PRD-declared invariants. They use the framework's
generic validators (is_valid_uuid, is_iso8601_timestamp) internally.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_LOYALTY_TIERS = ["STANDARD", "PREFERRED", "WHOLESALE"]
_SPECIES = ["BEEF", "PORK", "LAMB", "POULTRY"]
_LOT_STATUSES = ["AVAILABLE", "AGING", "ON_HOLD", "DEPLETED", "DISCARDED"]
_LOCKER_STATUSES = ["OPERATIONAL", "QUARANTINED"]
_SHARE_STATUSES = ["OPEN", "FULLY_CLAIMED", "BROKEN_DOWN", "CANCELLED"]
_CLAIM_STATUSES = ["ACTIVE", "CANCELLED"]
_ORDER_STATUSES = ["PLACED", "CONFIRMED", "FILLED", "SHORT_FILLED", "CANCELLED"]
_LINE_STATUSES = ["PENDING", "DRAWN", "SHORTED"]
_DRAW_STATUSES = ["COMMITTED", "REVERTED"]
_BATCH_STATUSES = ["DRAFT", "RESERVED", "PRODUCED", "CANCELLED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["phone"], str)
    assert data["loyalty_tier"] in _LOYALTY_TIERS
    assert isinstance(data["store_credit_cents"], int) and data["store_credit_cents"] >= 0


def assert_cut_type(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["species"] in _SPECIES
    assert isinstance(data["base_price_cents_per_kg"], int) and data["base_price_cents_per_kg"] >= 1
    assert isinstance(data["is_grind"], bool)
    assert isinstance(data["requires_dry_age"], bool)


def assert_pricing_policy(data: dict):
    _assert_common(data)
    assert isinstance(data["is_active"], bool)
    assert isinstance(data["bulk_threshold_g"], int) and data["bulk_threshold_g"] >= 1


def assert_inventory_lot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["cut_type_id"])
    assert isinstance(data["received_weight_g"], int) and data["received_weight_g"] >= 1
    assert isinstance(data["remaining_weight_g"], int) and data["remaining_weight_g"] >= 0
    assert data["remaining_weight_g"] <= data["received_weight_g"]
    assert data["lot_status"] in _LOT_STATUSES


def assert_locker(data: dict):
    _assert_common(data)
    assert isinstance(data["capacity_g"], int) and data["capacity_g"] >= 1
    assert isinstance(data["occupied_g"], int) and data["occupied_g"] >= 0
    assert data["locker_status"] in _LOCKER_STATUSES
    assert data["max_temp_c"] >= data["min_temp_c"]


def assert_temp_reading(data: dict):
    """Append-only log: id + created_at only; no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "TempReading is append-only and carries no version"
    assert "updated_at" not in data, "TempReading is append-only and carries no updated_at"
    assert isinstance(data["in_band"], bool)
    assert isinstance(data["triggered_quarantine"], bool)


def assert_animal_share(data: dict):
    _assert_common(data)
    assert data["species"] in _SPECIES
    assert isinstance(data["carcass_weight_g"], int) and data["carcass_weight_g"] >= 1
    assert isinstance(data["claimed_fraction_x4"], int) and 0 <= data["claimed_fraction_x4"] <= 4
    assert isinstance(data["remaining_carcass_g"], int) and data["remaining_carcass_g"] >= 0
    assert data["share_status"] in _SHARE_STATUSES


def assert_share_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["animal_share_id"])
    assert is_valid_uuid(data["customer_id"])
    assert data["fraction"] in ["QUARTER", "HALF"]
    assert isinstance(data["deposit_paid_cents"], int) and data["deposit_paid_cents"] >= 0
    assert data["claim_status"] in _CLAIM_STATUSES


def assert_custom_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["customer_id"])
    assert data["order_kind"] in ["STANDARD", "HOLIDAY"]
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0
    assert isinstance(data["estimated_total_cents"], int)
    assert data["order_status"] in _ORDER_STATUSES


def assert_order_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["cut_type_id"])
    assert isinstance(data["ordered_weight_g"], int) and data["ordered_weight_g"] >= 1
    assert isinstance(data["est_line_cents"], int)
    assert data["line_status"] in _LINE_STATUSES


def assert_lot_draw(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["inventory_lot_id"])
    assert isinstance(data["weight_g"], int) and data["weight_g"] >= 1
    assert data["draw_status"] in _DRAW_STATUSES


def assert_sausage_batch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["output_cut_type_id"])
    assert isinstance(data["planned_output_g"], int) and data["planned_output_g"] >= 1
    assert data["batch_status"] in _BATCH_STATUSES


def assert_holiday_window(data: dict):
    _assert_common(data)
    assert isinstance(data["capacity_g"], int) and data["capacity_g"] >= 1
    assert isinstance(data["committed_g"], int) and data["committed_g"] >= 0


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------
def assert_share_carcass_invariant(data: dict):
    """remaining_carcass_g must equal floor(carcass_weight_g * (4 - x4) / 4)."""
    expected = (data["carcass_weight_g"] * (4 - data["claimed_fraction_x4"])) // 4
    assert data["remaining_carcass_g"] == expected, (
        f"remaining_carcass_g {data['remaining_carcass_g']} != expected {expected}"
    )
