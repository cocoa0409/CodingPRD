"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS

# Unique-code counter so independently created SKUs across a test don't collide
# on the (client_id, code) uniqueness constraint.
_code_counter = {"n": 0}


def _next_code(prefix="SKU"):
    _code_counter["n"] += 1
    return f"{prefix}{_code_counter['n']}"


def create_client_payload(**overrides) -> dict:
    """Required: name, storage_rate_per_pallet_cents, handling_rate_per_order_cents.
    Optional (default 0): handling_rate_per_extra_unit_cents,
    handling_surcharge_per_extra_carton_cents, carrier_discount_bps."""
    defaults = {
        "name": "Test Client",
        "storage_rate_per_pallet_cents": TEST_DEFAULTS["STORAGE_RATE_PER_PALLET_CENTS"],
        "handling_rate_per_order_cents": TEST_DEFAULTS["HANDLING_RATE_PER_ORDER_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_sku_payload(**overrides) -> dict:
    """Required: code, unit_volume_cc. Optional: unit_cost_cents, hazmat."""
    defaults = {
        "code": _next_code(),
        "unit_volume_cc": TEST_DEFAULTS["UNIT_VOLUME_CC"],
        "hazmat": False,
    }
    defaults.update(overrides)
    return defaults


def create_bin_payload(**overrides) -> dict:
    """Required: location_code, bin_type, capacity_cc."""
    _code_counter["n"] += 1
    defaults = {
        "location_code": f"BIN-{_code_counter['n']}",
        "bin_type": "GENERAL",
        "capacity_cc": TEST_DEFAULTS["LARGE_BIN_CAPACITY_CC"],
    }
    defaults.update(overrides)
    return defaults


def create_receipt_payload(sku_id, bin_id, **overrides) -> dict:
    """Required: sku_id, bin_id, expected_qty."""
    defaults = {
        "sku_id": sku_id,
        "bin_id": bin_id,
        "expected_qty": overrides.pop("expected_qty", 1),
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(lines, **overrides) -> dict:
    """Required: ship_to_zone, lines. `lines` is a list of {sku_id, qty}."""
    defaults = {
        "ship_to_zone": overrides.pop("ship_to_zone", 2),
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def order_line(sku_id, qty) -> dict:
    return {"sku_id": sku_id, "qty": qty}


def carton_entry(packed_units) -> dict:
    return {"packed_units": packed_units}


def create_return_payload(order_id, sku_id, bin_id, qty, **overrides) -> dict:
    """Required: order_id, sku_id, bin_id, qty."""
    defaults = {
        "order_id": order_id,
        "sku_id": sku_id,
        "bin_id": bin_id,
        "qty": qty,
    }
    defaults.update(overrides)
    return defaults


def create_cycle_count_payload(lot_id, expected_lot_version, counted_qty, **overrides) -> dict:
    """Required: lot_id, expected_lot_version, counted_qty."""
    defaults = {
        "lot_id": lot_id,
        "expected_lot_version": expected_lot_version,
        "counted_qty": counted_qty,
    }
    defaults.update(overrides)
    return defaults
