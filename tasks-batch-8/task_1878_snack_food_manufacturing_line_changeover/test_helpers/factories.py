"""Payload factories — one per entity, input fields only."""

PRODUCT_DEFAULTS = {
    "name": "Plain Chips",
    "process_type": "FRYER",
    "allergen_profile": [],
    "flavor_group": "PLAIN",
    "declared_net_weight_g": 100.0,
    "tne_g": 1.5,
    "giveaway_target_pct": 2.0,
    "giveaway_max_pct": 3.0,
    "shelf_life_days": 30,
    "seasoning_target_pct": 4.0,
    "fry_target_temp_c": 180.0,
    "standard_oil_price_cents_per_gal": 500,
    "case_revenue_cents": 4000,
    "min_margin_cents_per_case": 1000,
    "bags_per_case": 12,
}


def create_product_payload(**overrides) -> dict:
    defaults = dict(PRODUCT_DEFAULTS)
    defaults.update(overrides)
    return defaults


LINE_DEFAULTS = {
    "name": "Line 1",
    "line_type": "BOTH",
    "oil_capacity_gallons": 100,
}


def create_line_payload(**overrides) -> dict:
    defaults = dict(LINE_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_run_payload(line_id, product_id, expected_line_version, **overrides) -> dict:
    defaults = {
        "line_id": line_id,
        "product_id": product_id,
        "scheduled_start": "2026-08-02T08:00:00Z",
        "scheduled_end": "2026-08-02T10:00:00Z",
        "lbs_planned": 100,
        "cases_planned": 10,
        "expected_line_version": expected_line_version,
    }
    defaults.update(overrides)
    return defaults


def create_weight_check_payload(run_id, **overrides) -> dict:
    defaults = {
        "run_id": run_id,
        "bag_weight_g": 100.0,
        "lbs_fried_since_last_check": 100,
        "avg_fry_temp_c": 180.0,
    }
    defaults.update(overrides)
    return defaults


def complete_run_payload(**overrides) -> dict:
    defaults = {
        "lbs_produced": 100,
        "cases_produced": 10,
        "rejected_cases": 0,
        "seasoning_actual_pct": 4.0,
    }
    defaults.update(overrides)
    return defaults


def create_changeover_payload(line_id, to_product_id, **overrides) -> dict:
    defaults = {"line_id": line_id, "to_product_id": to_product_id}
    defaults.update(overrides)
    return defaults


def create_oil_movement_payload(fryer_oil_id, expected_oil_version, **overrides) -> dict:
    defaults = {
        "fryer_oil_id": fryer_oil_id,
        "movement_type": "TOP_OFF",
        "gallons": 1,
        "unit_price_cents_per_gal": 600,
        "expected_oil_version": expected_oil_version,
    }
    defaults.update(overrides)
    # unit_price_cents_per_gal is forbidden (not merely nullable) for DISCARD
    # and FILTRATION, so an explicit None override omits the key entirely.
    if defaults.get("unit_price_cents_per_gal") is None:
        defaults.pop("unit_price_cents_per_gal", None)
    return defaults


def create_shipment_payload(run_id, **overrides) -> dict:
    defaults = {
        "run_id": run_id,
        "cases": 1,
        "requested_route": "DSD",
    }
    defaults.update(overrides)
    return defaults


def create_promo_window_payload(product_id, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "quota_total_cases": 10,
        "window_start_date": "2026-08-01",
        "window_end_date": "2026-08-31",
    }
    defaults.update(overrides)
    return defaults


def create_display_case_payload(promo_window_id, run_id, **overrides) -> dict:
    defaults = {
        "promo_window_id": promo_window_id,
        "run_id": run_id,
        "cases_planned": 1,
    }
    defaults.update(overrides)
    return defaults


def create_co_manufacturer_payload(**overrides) -> dict:
    defaults = {"name": "TollCo"}
    defaults.update(overrides)
    return defaults


def create_agreement_payload(co_manufacturer_id, **overrides) -> dict:
    defaults = {
        "co_manufacturer_id": co_manufacturer_id,
        "weekly_capacity_lbs": 10000,
        "rate_per_lb_cents": 50,
        "budget_cents": 1000000,
    }
    defaults.update(overrides)
    return defaults


def create_slot_payload(agreement_id, product_id, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "product_id": product_id,
        "week_start_date": "2026-09-07",
        "reserved_lbs": 100,
    }
    defaults.update(overrides)
    return defaults
