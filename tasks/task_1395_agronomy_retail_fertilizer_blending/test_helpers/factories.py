"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS as TD


def create_grower_payload(**overrides) -> dict:
    defaults = {"legal_name": "Test Farms", "credit_limit_cents": 10_000_000}
    defaults.update(overrides)
    return defaults


def create_field_payload(**overrides) -> dict:
    defaults = {"name": "Test Field", "acres": 50, "watershed_zone": "STANDARD"}
    defaults.update(overrides)
    return defaults


def create_soil_test_payload(**overrides) -> dict:
    defaults: dict = {}
    defaults.update(overrides)
    return defaults


def post_results_payload(**overrides) -> dict:
    defaults = {"p_ppm": TD["SOIL_P_PPM"], "k_ppm": TD["SOIL_K_PPM"], "ph": TD["SOIL_PH"]}
    defaults.update(overrides)
    return defaults


def create_recommendation_payload(**overrides) -> dict:
    defaults = {
        "crop": "CORN",
        "yield_goal_bu_per_acre": 220,
        "rate_variant": "BUILD_RATE",
        "valid_until": TD["REC_VALID_UNTIL"],
    }
    defaults.update(overrides)
    return defaults


def create_nutrient_plan_payload(**overrides) -> dict:
    defaults = {
        "crop_year": 2026,
        "n_cap_lbs_per_acre": 300,
        "valid_from": TD["NMP_VALID_FROM"],
        "valid_to": TD["NMP_VALID_TO"],
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(**overrides) -> dict:
    defaults = {
        "permit_type": "FERTILIZER_STORAGE",
        "site_code": TD["SITE_CODE"],
        "setback_ft": 200,
        "max_storage_tons": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "name": "UREA 46-0-0",
        "analysis_n_pct": 46,
        "analysis_p2o5_pct": 0,
        "analysis_k2o_pct": 0,
        "form": "DRY",
    }
    defaults.update(overrides)
    return defaults


def create_price_sheet_payload(**overrides) -> dict:
    defaults = {
        "season": "FALL",
        "price_per_ton_cents": TD["UREA_PRICE_CENTS"],
        "effective_from": TD["SHEET_FROM"],
        "effective_to": TD["SHEET_TO"],
    }
    defaults.update(overrides)
    return defaults


def receive_lot_payload(**overrides) -> dict:
    defaults = {
        "warehouse_code": "WH-A",
        "received_tons": 20,
        "lot_cost_cents_per_ton": 40000,
    }
    defaults.update(overrides)
    return defaults


def create_prepay_program_payload(**overrides) -> dict:
    defaults = {
        "name": "FALL-2026 PREPAY",
        "season": "FALL",
        "enrollment_open_on": TD["PREPAY_ENROLL_OPEN"],
        "enrollment_close_on": TD["PREPAY_ENROLL_CLOSE"],
        "funding_deadline": TD["PREPAY_FUNDING_DEADLINE"],
        "deposit_pct": TD["PREPAY_DEPOSIT_PCT"],
        "discount_pct": TD["PREPAY_DISCOUNT_PCT"],
        "default_penalty_pct": TD["PREPAY_PENALTY_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_prepay_contract_payload(**overrides) -> dict:
    defaults = {"committed_tons": 20}
    defaults.update(overrides)
    return defaults


def create_blend_order_payload(**overrides) -> dict:
    defaults = {"price_mode": "FLOATING"}
    defaults.update(overrides)
    return defaults


def blend_line_payload(**overrides) -> dict:
    defaults = {"target_rate_lbs_per_acre": 348.1}
    defaults.update(overrides)
    return defaults


def create_blender_payload(**overrides) -> dict:
    defaults = {
        "name": "BLENDER-1",
        "site_code": TD["SITE_CODE"],
        "capacity_tons_per_hour": 40,
        "form_supported": "BOTH",
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(**overrides) -> dict:
    defaults = {
        "scheduled_start": "2026-08-05T08:00:00Z",
        "scheduled_end": "2026-08-05T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_truck_payload(**overrides) -> dict:
    defaults = {"name": "TRUCK-1", "capacity_tons": 25}
    defaults.update(overrides)
    return defaults


def create_delivery_route_payload(**overrides) -> dict:
    defaults = {"route_date": "2026-08-20"}
    defaults.update(overrides)
    return defaults


def add_stop_payload(**overrides) -> dict:
    defaults = {
        "sequence": 1,
        "window_start": "2026-08-20T08:00:00Z",
        "window_end": "2026-08-20T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults
