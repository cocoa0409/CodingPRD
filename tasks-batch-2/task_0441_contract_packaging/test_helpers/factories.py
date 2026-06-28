"""Payload factories — one per entity, input fields only.

Each factory provides PRD-faithful defaults and accepts **overrides.
Field names match the PRD exactly.
"""


def create_customer_payload(**overrides) -> dict:
    defaults = {"name": "Acme Foods", "code": "ACME"}
    defaults.update(overrides)
    return defaults


def create_component_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "sku": "ALMOND",
        "name": "Roasted Almonds",
        "kind": "INGREDIENT",
    }
    defaults.update(overrides)
    return defaults


def receive_lot_payload(**overrides) -> dict:
    defaults = {
        "supplier_lot_code": "SL-1",
        "received_qty": 500,
        "expiration_date": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_recipe_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "name": "Granola Bars",
        "target_fill_weight_g": 200,
        "fill_tolerance_pct": 5,
        "shelf_life_days": 90,
    }
    defaults.update(overrides)
    return defaults


def add_bom_line_payload(component_id, expected_recipe_version, **overrides) -> dict:
    defaults = {
        "component_id": component_id,
        "qty_per_unit": 2,
        "expected_recipe_version": expected_recipe_version,
    }
    defaults.update(overrides)
    return defaults


def create_production_line_payload(**overrides) -> dict:
    defaults = {"name": "Line A", "rated_units_per_hour": 50}
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    defaults = {"name": "Day Crew"}
    defaults.update(overrides)
    return defaults


def schedule_run_payload(recipe_id, line_id, crew_id, **overrides) -> dict:
    defaults = {
        "recipe_id": recipe_id,
        "line_id": line_id,
        "crew_id": crew_id,
        "planned_units": 100,
        "scheduled_start": "2026-06-01T08:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def start_run_payload(expected_line_version, **overrides) -> dict:
    defaults = {"expected_line_version": expected_line_version}
    defaults.update(overrides)
    return defaults


def complete_run_payload(actual_units_good=0, actual_units_scrapped=0, **overrides) -> dict:
    defaults = {
        "actual_units_good": actual_units_good,
        "actual_units_scrapped": actual_units_scrapped,
    }
    defaults.update(overrides)
    return defaults


def checkweigh_sample_payload(measured_weight_g, **overrides) -> dict:
    defaults = {"measured_weight_g": measured_weight_g}
    defaults.update(overrides)
    return defaults
