"""Payload factories — one per entity, input fields only.

DEFAULTS pins the standard catalog used across the tests: a 4000-psi pump mix
(564 lb/yd3 cement, design w/c 0.45, max w/c 0.50) and a price list with
base 15000 cents/yd3, min load 4.0, short-load fee 7500, 60 free wait minutes
at 250/min capped at 15000, and a 0.10 Saturday surcharge.
"""

DEFAULTS = {
    "PLANT_NAME": "Plant A",
    "BATCH_CYCLE_MINUTES": 30,
    "DAILY_CAPACITY_YD3": 400,
    "MIX_CODE": "M4000",
    "MIX_NAME": "4000 psi pump mix",
    "DESIGN_STRENGTH_PSI": 4000,
    "SLUMP_IN": 4.0,
    "CEMENT_CONTENT_LB_PER_YD3": 564,
    "DESIGN_WC_RATIO": 0.45,
    "MAX_WC_RATIO": 0.50,
    "BASE_PRICE_PER_YD3_CENTS": 15000,
    "ESCALATION_BASE_INDEX_POINTS": 100.0,
    "MIN_LOAD_YD3": 4.0,
    "SHORT_LOAD_FEE_CENTS": 7500,
    "WAIT_FREE_MINUTES": 60,
    "WAIT_RATE_PER_MINUTE_CENTS": 250,
    "WAIT_FEE_CAP_CENTS": 15000,
    "SATURDAY_SURCHARGE_PCT": 0.10,
    "CUSTOMER_NAME": "Cust A",
    "CREDIT_LIMIT_CENTS": 100000000,
    "FLEET_NUMBER": "T1",
    "TRUCK_CAPACITY_YD3": 10.0,
    "QTY_YD3": 8.0,
    "POUR_DATE": "2026-08-15",
    "POUR_WINDOW_START": "07:00",
    "POUR_WINDOW_END": "10:00",
    "ORDER_SLUMP_IN": 4.5,
    "NUM_CYLINDERS": 3,
}


def create_plant_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PLANT_NAME"],
        "batch_cycle_minutes": DEFAULTS["BATCH_CYCLE_MINUTES"],
        "daily_capacity_yd3": DEFAULTS["DAILY_CAPACITY_YD3"],
    }
    defaults.update(overrides)
    return defaults


def create_mix_design_payload(plant_id, **overrides) -> dict:
    defaults = {
        "plant_id": plant_id,
        "code": DEFAULTS["MIX_CODE"],
        "name": DEFAULTS["MIX_NAME"],
        "design_strength_psi": DEFAULTS["DESIGN_STRENGTH_PSI"],
        "slump_in": DEFAULTS["SLUMP_IN"],
        "cement_content_lb_per_yd3": DEFAULTS["CEMENT_CONTENT_LB_PER_YD3"],
        "design_wc_ratio": DEFAULTS["DESIGN_WC_RATIO"],
        "max_wc_ratio": DEFAULTS["MAX_WC_RATIO"],
        "admixtures": [
            {"admixture_code": "AEA", "dose_oz_per_cwt": 1.55},
            {"admixture_code": "WR", "dose_oz_per_cwt": 2.65},
        ],
    }
    defaults.update(overrides)
    return defaults


def create_price_list_payload(plant_id, mix_design_id, expected_plant_version, **overrides) -> dict:
    defaults = {
        "plant_id": plant_id,
        "mix_design_id": mix_design_id,
        "expected_plant_version": expected_plant_version,
        "base_price_per_yd3_cents": DEFAULTS["BASE_PRICE_PER_YD3_CENTS"],
        "escalation_base_index_points": DEFAULTS["ESCALATION_BASE_INDEX_POINTS"],
        "min_load_yd3": DEFAULTS["MIN_LOAD_YD3"],
        "short_load_fee_cents": DEFAULTS["SHORT_LOAD_FEE_CENTS"],
        "wait_free_minutes": DEFAULTS["WAIT_FREE_MINUTES"],
        "wait_rate_per_minute_cents": DEFAULTS["WAIT_RATE_PER_MINUTE_CENTS"],
        "wait_fee_cap_cents": DEFAULTS["WAIT_FEE_CAP_CENTS"],
        "saturday_surcharge_pct": DEFAULTS["SATURDAY_SURCHARGE_PCT"],
        "activate": True,
    }
    defaults.update(overrides)
    return defaults


def create_cement_price_index_payload(plant_id, effective_month, index_points, **overrides) -> dict:
    defaults = {
        "plant_id": plant_id,
        "effective_month": effective_month,
        "index_points": index_points,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CUSTOMER_NAME"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_truck_payload(plant_id, **overrides) -> dict:
    defaults = {
        "plant_id": plant_id,
        "fleet_number": DEFAULTS["FLEET_NUMBER"],
        "capacity_yd3": DEFAULTS["TRUCK_CAPACITY_YD3"],
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(plant_id, mix_design_id, **overrides) -> dict:
    defaults = {
        "plant_id": plant_id,
        "mix_design_id": mix_design_id,
        "qty_yd3": DEFAULTS["QTY_YD3"],
        "pour_date": DEFAULTS["POUR_DATE"],
        "pour_window_start": DEFAULTS["POUR_WINDOW_START"],
        "pour_window_end": DEFAULTS["POUR_WINDOW_END"],
        "slump_in": DEFAULTS["ORDER_SLUMP_IN"],
    }
    defaults.update(overrides)
    return defaults


def schedule_load_payload(qty_yd3, expected_order_version, **overrides) -> dict:
    defaults = {
        "qty_yd3": qty_yd3,
        "expected_order_version": expected_order_version,
    }
    defaults.update(overrides)
    return defaults


def batch_load_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def complete_load_payload(discharged_qty_yd3, **overrides) -> dict:
    defaults = {"discharged_qty_yd3": discharged_qty_yd3}
    defaults.update(overrides)
    return defaults


def return_load_payload(discharged_qty_yd3, returned_qty_yd3, disposition="RECYCLED", **overrides) -> dict:
    defaults = {
        "discharged_qty_yd3": discharged_qty_yd3,
        "returned_qty_yd3": returned_qty_yd3,
        "disposition": disposition,
    }
    defaults.update(overrides)
    return defaults


def washout_payload(washout_water_gal, **overrides) -> dict:
    defaults = {"washout_water_gal": washout_water_gal}
    defaults.update(overrides)
    return defaults


def water_addition_payload(gallons, customer_authorized, **overrides) -> dict:
    defaults = {"gallons": gallons, "customer_authorized": customer_authorized}
    defaults.update(overrides)
    return defaults


def cylinder_set_payload(num_cylinders=None, **overrides) -> dict:
    defaults = {"num_cylinders": num_cylinders or DEFAULTS["NUM_CYLINDERS"]}
    defaults.update(overrides)
    return defaults


def break_payload(break_type, strength_psi, **overrides) -> dict:
    defaults = {"break_type": break_type, "strength_psi": strength_psi}
    defaults.update(overrides)
    return defaults
