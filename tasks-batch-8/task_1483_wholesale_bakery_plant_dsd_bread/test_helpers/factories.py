"""Payload factories — one per entity, input fields only (PRD §3)."""


def create_plant_payload(**overrides) -> dict:
    defaults = {
        "name": "Plant Alpha",
        "baseline_flour_index": 400,
        "baseline_butter_index": 600,
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(plant_id: str, **overrides) -> dict:
    defaults = {
        "plant_id": plant_id,
        "sku": "SKU-A",
        "name": "White Pan 500",
        "allergen_class": "NONE",
        "unit_weight_g": 500,
        "shelf_life_hours": 48,
        "base_price_cents": 199,
        "flour_share_pct": 0.30,
        "butter_share_pct": 0.10,
        "batch_capacity_units": 240,
    }
    defaults.update(overrides)
    return defaults


def create_store_payload(plant_id: str, **overrides) -> dict:
    defaults = {
        "plant_id": plant_id,
        "name": "Store S1",
        "lead_time_hours": 48,
        "min_remaining_life_hours_on_delivery": 12,
        "shelf_capacity_units": 100,
        "stale_credit_tier": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_driver_payload(plant_id: str, **overrides) -> dict:
    defaults = {
        "plant_id": plant_id,
        "name": "Driver One",
    }
    defaults.update(overrides)
    return defaults


def create_line_payload(plant_id: str, **overrides) -> dict:
    defaults = {
        "plant_id": plant_id,
        "line_code": "L1",
        "hourly_capacity_units": 500,
    }
    defaults.update(overrides)
    return defaults


def create_store_order_payload(store_id: str, product_id: str, qty: int = 100, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "delivery_date": "2026-08-10",
        "lines": [{"product_id": product_id, "qty": qty}],
    }
    defaults.update(overrides)
    return defaults


def create_production_plan_payload(plant_id: str, expected_plant_version: int, **overrides) -> dict:
    defaults = {
        "plant_id": plant_id,
        "bake_date": "2026-08-09",
        "expected_plant_version": expected_plant_version,
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(
    production_plan_id: str,
    line_id: str,
    product_id: str,
    expected_production_plan_version: int,
    **overrides,
) -> dict:
    defaults = {
        "production_plan_id": production_plan_id,
        "line_id": line_id,
        "product_id": product_id,
        "qty_units": 100,
        "scheduled_start_at": "2026-08-09T07:00:00Z",
        "scheduled_end_at": "2026-08-09T09:00:00Z",
        "expected_production_plan_version": expected_production_plan_version,
    }
    defaults.update(overrides)
    return defaults


def create_sanitation_cycle_payload(line_id: str, **overrides) -> dict:
    defaults = {
        "line_id": line_id,
        "to_allergen_class": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(plant_id: str, driver_id: str, **overrides) -> dict:
    defaults = {
        "plant_id": plant_id,
        "driver_id": driver_id,
        "route_date": "2026-08-10",
        "window_start_at": "2026-08-10T08:00:00Z",
        "window_end_at": "2026-08-10T12:00:00Z",
        "truck_capacity_units": 500,
    }
    defaults.update(overrides)
    return defaults


def create_route_stop_payload(
    route_id: str,
    store_order_id: str,
    planned_units: int,
    batch_ids: list,
    **overrides,
) -> dict:
    defaults = {
        "route_id": route_id,
        "store_order_id": store_order_id,
        "planned_units": planned_units,
        "batch_ids": batch_ids,
    }
    defaults.update(overrides)
    return defaults


def create_stale_return_payload(
    store_id: str,
    route_stop_id: str,
    lines: list,
    **overrides,
) -> dict:
    defaults = {
        "store_id": store_id,
        "route_stop_id": route_stop_id,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_thrift_sale_payload(product_id: str, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "units": 1,
        "unit_price_cents": 100,
    }
    defaults.update(overrides)
    return defaults


def create_ingredient_index_payload(plant_id: str, **overrides) -> dict:
    defaults = {
        "plant_id": plant_id,
        "ingredient": "FLOUR",
        "period": "2026-08",
        "forecast_value": 440,
    }
    defaults.update(overrides)
    return defaults


def create_surcharge_schedule_payload(product_id: str, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "period": "2026-08",
    }
    defaults.update(overrides)
    return defaults
