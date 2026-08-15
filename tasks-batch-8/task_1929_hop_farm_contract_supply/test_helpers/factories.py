"""Payload factories — one per write endpoint, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "FIELD_NAME": "F1",
    "FIELD_ACREAGE": 100,
    "KILN_NAME": "K1",
    "CROP_YEAR": 2026,
    "VARIETY": "CASCADE",
    "PLANNED_ACREAGE": 40,
    "BREWERY_NAME": "BrewCo",
    "TERM_START_YEAR": 2026,
    "TERM_END_YEAR": 2028,
    "ANNUAL_VOLUME_LBS": 736,
    "BASE_PRICE_CENTS_PER_LB": 500,
    "ALPHA_FLOOR_PCT": 12.0,
    "ALPHA_PREMIUM_CENTS_PER_POINT": 40,
    "ALPHA_DISCOUNT_CENTS_PER_POINT": 60,
    "STORAGE_ROOM": "R1",
    "BUYER_NAME": "CraftBrew",
    "SPOT_PRICE_CENTS_PER_LB": 650,
    "BUYER_CREDIT_LIMIT_CENTS": 1_000_000,
    "PRICE_ELECTION_CENTS_PER_LB": 300,
}


def create_field_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["FIELD_NAME"],
        "acreage": DEFAULTS["FIELD_ACREAGE"],
    }
    defaults.update(overrides)
    return defaults


def create_kiln_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["KILN_NAME"]}
    defaults.update(overrides)
    return defaults


def create_planting_plan_payload(field_id: str, **overrides) -> dict:
    defaults = {
        "field_id": field_id,
        "crop_year": DEFAULTS["CROP_YEAR"],
        "variety": DEFAULTS["VARIETY"],
        "planned_acreage": DEFAULTS["PLANNED_ACREAGE"],
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(**overrides) -> dict:
    defaults = {
        "brewery_name": DEFAULTS["BREWERY_NAME"],
        "variety": DEFAULTS["VARIETY"],
        "term_start_year": DEFAULTS["TERM_START_YEAR"],
        "term_end_year": DEFAULTS["TERM_END_YEAR"],
        "annual_volume_lbs": DEFAULTS["ANNUAL_VOLUME_LBS"],
        "base_price_cents_per_lb": DEFAULTS["BASE_PRICE_CENTS_PER_LB"],
        "alpha_floor_pct": DEFAULTS["ALPHA_FLOOR_PCT"],
        "alpha_premium_cents_per_point": DEFAULTS["ALPHA_PREMIUM_CENTS_PER_POINT"],
        "alpha_discount_cents_per_point": DEFAULTS["ALPHA_DISCOUNT_CENTS_PER_POINT"],
    }
    defaults.update(overrides)
    return defaults


def create_amendment_payload(expected_contract_version: int, **overrides) -> dict:
    defaults = {"expected_contract_version": expected_contract_version}
    defaults.update(overrides)
    return defaults


def create_harvest_lot_payload(planting_plan_id: str, wet_lbs: int, **overrides) -> dict:
    defaults = {"planting_plan_id": planting_plan_id, "wet_lbs": wet_lbs}
    defaults.update(overrides)
    return defaults


def create_load_kiln_payload(kiln_id: str, kiln_window_start: str,
                             kiln_window_end: str) -> dict:
    return {
        "kiln_id": kiln_id,
        "kiln_window_start": kiln_window_start,
        "kiln_window_end": kiln_window_end,
    }


def create_redry_payload(kiln_window_start: str, kiln_window_end: str) -> dict:
    return {
        "kiln_window_start": kiln_window_start,
        "kiln_window_end": kiln_window_end,
    }


def create_finish_drying_payload(dried_lbs: int) -> dict:
    return {"dried_lbs": dried_lbs}


def create_lab_test_payload(harvest_lot_id: str, test_type: str, alpha_pct: float) -> dict:
    return {
        "harvest_lot_id": harvest_lot_id,
        "test_type": test_type,
        "alpha_pct": alpha_pct,
    }


def create_pellet_lot_payload(source_lot_ids: list, storage_room: str = "R1") -> dict:
    return {"source_lot_ids": list(source_lot_ids), "storage_room": storage_room}


def create_allocation_run_payload(crop_year: int = 2026, variety: str = "CASCADE") -> dict:
    return {"crop_year": crop_year, "variety": variety}


def create_spot_sale_payload(pellet_lot_id: str, **overrides) -> dict:
    defaults = {
        "pellet_lot_id": pellet_lot_id,
        "buyer_name": DEFAULTS["BUYER_NAME"],
        "price_cents_per_lb": DEFAULTS["SPOT_PRICE_CENTS_PER_LB"],
        "buyer_credit_limit_cents": DEFAULTS["BUYER_CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_sample_payload(pellet_lot_id: str, brewery_name: str = "CraftBrew") -> dict:
    return {"pellet_lot_id": pellet_lot_id, "brewery_name": brewery_name}


def create_insurance_claim_payload(planting_plan_id: str, **overrides) -> dict:
    defaults = {
        "planting_plan_id": planting_plan_id,
        "price_election_cents_per_lb": DEFAULTS["PRICE_ELECTION_CENTS_PER_LB"],
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
