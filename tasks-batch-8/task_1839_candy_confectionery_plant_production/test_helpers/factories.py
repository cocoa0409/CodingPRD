"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "COMPONENT_SKU": "BOX-24",
    "COMPONENT_NAME": "24pc box",
    "UNITS_PER_COMPONENT": 10,
    "LEAD_TIME_DAYS": 14,
    "PRODUCT_SKU": "NOVELTY",
    "PRODUCT_NAME": "Novelty",
    "BASE_PRICE_CENTS": 800,
    "UNIT_WEIGHT_GRAMS": 100,
    "SHELF_LIFE_DAYS": 200,
    "RECIPE_NAME": "Novelty mass",
    "SHAPE_CODE": "STAR",
    "CAVITY_COUNT": 60,
    "LINE_NAME": "LINE-1",
    "SEASON_CODE": "BASE",
    "TARGET_UNITS": 5000,
    "PLANNED_UNITS": 500,
    "SCHEDULED_START": "2026-09-05T08:00:00Z",
    "SCHEDULED_END": "2026-09-05T16:00:00Z",
    "COOK_TEMP": 85,
    "TEMPER_EXIT": 29,
}


def create_product_payload(packaging_component_id, **overrides) -> dict:
    defaults = {
        "sku_code": DEFAULTS["PRODUCT_SKU"],
        "name": DEFAULTS["PRODUCT_NAME"],
        "product_type": "STANDARD",
        "brand": "OWN",
        "base_price_cents": DEFAULTS["BASE_PRICE_CENTS"],
        "unit_weight_grams": DEFAULTS["UNIT_WEIGHT_GRAMS"],
        "shelf_life_days": DEFAULTS["SHELF_LIFE_DAYS"],
        "packaging_component_id": packaging_component_id,
    }
    defaults.update(overrides)
    return defaults


def create_recipe_payload(product_id, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "name": DEFAULTS["RECIPE_NAME"],
        "shape_code": DEFAULTS["SHAPE_CODE"],
        "cook_temp_min_c": 80,
        "cook_temp_max_c": 90,
        "temper_exit_min_c": 28,
        "temper_exit_max_c": 30,
        "allergens": [],
        "standard_yield_pct": 0.95,
    }
    defaults.update(overrides)
    return defaults


def create_gift_component_payload(gift_product_id, component_product_id,
                                  qty_per_set=1, **overrides) -> dict:
    defaults = {
        "gift_product_id": gift_product_id,
        "component_product_id": component_product_id,
        "qty_per_set": qty_per_set,
    }
    defaults.update(overrides)
    return defaults


def create_packaging_component_payload(**overrides) -> dict:
    defaults = {
        "sku_code": DEFAULTS["COMPONENT_SKU"],
        "name": DEFAULTS["COMPONENT_NAME"],
        "units_per_component": DEFAULTS["UNITS_PER_COMPONENT"],
        "lead_time_days": DEFAULTS["LEAD_TIME_DAYS"],
        "qty_on_hand": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_purchase_order_payload(order_qty=500, **overrides) -> dict:
    defaults = {"order_qty": order_qty}
    defaults.update(overrides)
    return defaults


def create_mold_payload(**overrides) -> dict:
    defaults = {
        "shape_code": DEFAULTS["SHAPE_CODE"],
        "cavity_count": DEFAULTS["CAVITY_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_production_line_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["LINE_NAME"]}
    defaults.update(overrides)
    return defaults


def create_changeover_payload(changeover_type, expected_line_version,
                              to_mold_id=None, target_allergens=None,
                              **overrides) -> dict:
    payload = {
        "changeover_type": changeover_type,
        "expected_line_version": expected_line_version,
    }
    if to_mold_id is not None:
        payload["to_mold_id"] = to_mold_id
    if target_allergens is not None:
        payload["target_allergens"] = list(target_allergens)
    payload.update(overrides)
    return payload


def create_seasonal_window_payload(**overrides) -> dict:
    defaults = {
        "season_code": DEFAULTS["SEASON_CODE"],
        "build_start": "2026-09-01T00:00:00Z",
        "build_end": "2026-10-15T00:00:00Z",
        "ship_start": "2026-11-01T00:00:00Z",
        "ship_end": "2026-12-26T00:00:00Z",
        "target_units": DEFAULTS["TARGET_UNITS"],
        "markdown_tiers": [],
    }
    defaults.update(overrides)
    return defaults


def create_production_run_payload(window_id, product_id, recipe_id, line_id,
                                  expected_window_version, **overrides) -> dict:
    defaults = {
        "window_id": window_id,
        "product_id": product_id,
        "recipe_id": recipe_id,
        "line_id": line_id,
        "run_type": "STANDARD",
        "planned_units": DEFAULTS["PLANNED_UNITS"],
        "scheduled_start": DEFAULTS["SCHEDULED_START"],
        "scheduled_end": DEFAULTS["SCHEDULED_END"],
        "expected_window_version": expected_window_version,
    }
    defaults.update(overrides)
    return defaults


def complete_run_payload(output_units, actual_cook_temp_c=DEFAULTS["COOK_TEMP"],
                         actual_temper_exit_c=DEFAULTS["TEMPER_EXIT"],
                         **overrides) -> dict:
    defaults = {
        "actual_cook_temp_c": actual_cook_temp_c,
        "actual_temper_exit_c": actual_temper_exit_c,
        "output_units": output_units,
    }
    defaults.update(overrides)
    return defaults


def create_quality_hold_payload(lot_id, defect_type="BLOOM", affected_units=1,
                                **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "defect_type": defect_type,
        "affected_units": affected_units,
    }
    defaults.update(overrides)
    return defaults


def disposition_payload(action="RELEASE", **overrides) -> dict:
    defaults = {"action": action}
    defaults.update(overrides)
    return defaults
