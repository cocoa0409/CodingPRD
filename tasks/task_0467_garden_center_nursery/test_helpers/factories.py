"""Payload factories — one per entity, input fields only."""


def create_nursery_payload(**overrides) -> dict:
    defaults = {"name": "Greenleaf", "site_hardiness_zone": 6}
    defaults.update(overrides)
    return defaults


def create_account_payload(**overrides) -> dict:
    defaults = {
        "account_type": "RETAIL",
        "display_name": "Walk-in",
        "ship_to_hardiness_zone": 6,
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": "DG-1",
        "name": "Test Product",
        "category": "DRY_GOOD",
        "unit": "EACH",
        "unit_price_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_live_plant_payload(**overrides) -> dict:
    defaults = {
        "sku": "PL-1",
        "name": "Test Plant",
        "category": "LIVE_PLANT",
        "unit": "EACH",
        "lifecycle_class": "PERENNIAL",
        "hardiness_min_zone": 1,
        "hardiness_max_zone": 13,
        "unit_price_cents": 1000,
        "warranty_days": 30,
        "warranty_pct": 50,
    }
    defaults.update(overrides)
    return defaults


def create_inventory_lot_payload(**overrides) -> dict:
    defaults = {"received_qty": 10, "unit_cost_cents": 250}
    defaults.update(overrides)
    return defaults


def create_care_log_payload(**overrides) -> dict:
    defaults = {"entry_type": "WATERING", "qty_lost": 0, "note": ""}
    defaults.update(overrides)
    return defaults


def create_promotion_payload(**overrides) -> dict:
    defaults = {
        "name": "Spring Days",
        "category_scope": "LIVE_PLANT",
        "discount_pct": 15,
        "starts_at": "2026-04-01T00:00:00Z",
        "ends_at": "2026-05-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(**overrides) -> dict:
    defaults = {
        "label": "T-1",
        "vehicle_type": "FLATBED",
        "capacity_cubic_yards": 50,
        "turnaround_minutes": 0,
    }
    defaults.update(overrides)
    return defaults


def add_line_payload(product_id, qty=1, **overrides) -> dict:
    defaults = {"product_id": product_id, "qty": qty}
    defaults.update(overrides)
    return defaults


def confirm_payload(expected_order_version, **overrides) -> dict:
    defaults = {"expected_order_version": expected_order_version}
    defaults.update(overrides)
    return defaults


def version_payload(expected_order_version, **overrides) -> dict:
    """Body for allocate/charge-account/pay/fulfill/cancel — version only."""
    defaults = {"expected_order_version": expected_order_version}
    defaults.update(overrides)
    return defaults


def create_special_order_payload(product_id, requested_qty=5, quoted_unit_cost_cents=1000, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "requested_qty": requested_qty,
        "quoted_unit_cost_cents": quoted_unit_cost_cents,
    }
    defaults.update(overrides)
    return defaults


def create_delivery_payload(vehicle_id, window_start, window_end, **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(claim_qty=1, **overrides) -> dict:
    defaults = {"claim_qty": claim_qty}
    defaults.update(overrides)
    return defaults
