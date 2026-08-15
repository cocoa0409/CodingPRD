"""Payload factories — one per entity, input fields only (PRD §3/§4)."""

_counter = {}


def _uniq(prefix: str) -> str:
    """Unique code per test process so one test can create several of a kind."""
    _counter[prefix] = _counter.get(prefix, 0) + 1
    return f"{prefix}-{_counter[prefix]:04d}"


def create_ingredient_lot_payload(**overrides) -> dict:
    defaults = {
        "lot_code": _uniq("LOT"),
        "corn_variety": "WHITE_CORN",
        "received_kg": 5000,
        "moisture_pct": 12.5,
    }
    defaults.update(overrides)
    return defaults


def create_nixtamal_batch_payload(ingredient_lot_id, **overrides) -> dict:
    defaults = {
        "ingredient_lot_id": ingredient_lot_id,
        "corn_kg": 1000,
        "lime_pct": 1.0,
        "cook_minutes": 90,
        "steep_target_hours": 8,
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku_code": _uniq("SKU"),
        "diameter_in": "D6",
        "count_per_pack": 12,
        "packs_per_case": 10,
        "unit_weight_g": 30,
        "channel": "RETAIL",
        "preservative_system": "PROPIONATE",
        "allergen_class": "CORN_ONLY",
        "weight_tolerance_pct": 2.0,
    }
    defaults.update(overrides)
    return defaults


def create_line_payload(**overrides) -> dict:
    defaults = {
        "line_code": _uniq("LINE"),
        "allergen_zone": "SHARED",
        "cases_per_hour": 100,
    }
    defaults.update(overrides)
    return defaults


def create_run_payload(product_id, line_id, expected_line_version, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "line_id": line_id,
        "planned_cases": 50,
        "start_at": "2026-08-02T10:00:00Z",
        "end_at": "2026-08-02T12:00:00Z",
        "expected_line_version": expected_line_version,
    }
    defaults.update(overrides)
    return defaults


def create_allocation_payload(nixtamal_batch_id, production_run_id, **overrides) -> dict:
    defaults = {
        "nixtamal_batch_id": nixtamal_batch_id,
        "production_run_id": production_run_id,
        "allocated_kg": 388.8,
    }
    defaults.update(overrides)
    return defaults


def create_changeover_payload(line_id, from_product_id, to_product_id, **overrides) -> dict:
    defaults = {
        "line_id": line_id,
        "from_product_id": from_product_id,
        "to_product_id": to_product_id,
    }
    defaults.update(overrides)
    return defaults


def create_pack_order_payload(production_run_id, **overrides) -> dict:
    defaults = {
        "production_run_id": production_run_id,
        "cases_planned": 20,
        "verification_method": "AVERAGE_WEIGHT",
    }
    defaults.update(overrides)
    return defaults


def create_weight_check_payload(cases_packed, **overrides) -> dict:
    defaults = {"cases_packed": cases_packed}
    defaults.update(overrides)
    return defaults


def create_mill_payload(**overrides) -> dict:
    defaults = {
        "milled_masa_kg": 1620,
        "measured_moisture_pct": 58,
        "masa_wasted_kg": 20,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "account_name": _uniq("CUST"),
        "channel": "RETAIL_GROCERY",
        "region": "TX-SOUTH",
        "base_weekly_cases": 40,
        "priority_tier": "A",
        "min_shelf_life_pct": 30,
    }
    defaults.update(overrides)
    return defaults


def create_seasonal_window_payload(**overrides) -> dict:
    defaults = {
        "window_name": _uniq("WIN"),
        "starts_on": "2026-08-10",
        "ends_on": "2026-08-16",
        "demand_multiplier": 1.5,
        "forecast_total_cases": 500,
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(**overrides) -> dict:
    defaults = {
        "route_code": _uniq("ROUTE"),
        "route_date": "2026-08-05",
        "region": "TX-SOUTH",
        "vehicle_capacity_cases": 100,
    }
    defaults.update(overrides)
    return defaults


def create_route_stop_payload(customer_id, pack_order_id, expected_route_version, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "pack_order_id": pack_order_id,
        "requested_cases": 10,
        "expected_route_version": expected_route_version,
    }
    defaults.update(overrides)
    return defaults
