"""Payload factories — one per creatable resource, input fields only (PRD §3)."""

ZERO_GRADE_ADJUSTMENTS = {
    "US_NO_1": 0,
    "US_NO_2": 0,
    "US_NO_3": 0,
    "US_NO_4": 0,
    "US_NO_5": 0,
    "SAMPLE": 0,
}

DEFAULTS = {
    "SEASON_NAME": "2026 Fall",
    "INTAKE_START_DATE": "2026-08-01",
    "INTAKE_END_DATE": "2026-10-31",
    "SPOT_DAILY_CAP": 2,
    "FARM_CODE": "FARM-001",
    "LEGAL_NAME": "Delta Farms",
    "BIN_CODE": "B-01",
    "BIN_CAPACITY_CWT": 500.00,
    "VARIETY": "LONG_GRAIN",
    "GROSS_WEIGHT_LBS": 22000,
    "TARE_WEIGHT_LBS": 12000,
    "SCHEDULED_DATE": "2026-08-10",
    "MOISTURE": 13.0,
    "SPOT_PRICE_CENTS_PER_CWT": 1300,
    "CONTRACTED_CWT": 400.00,
    "BASE_PRICE_CENTS_PER_CWT": 1500,
    "PERIOD_START_DATE": "2026-08-01",
    "PERIOD_END_DATE": "2026-08-31",
    "BUYER_NAME": "FeedCo",
    "BYPRODUCT_PRICE_CENTS_PER_CWT": 1800,
    "FUMIGANT_CODE": "PH3",
    "APPLICATOR_LICENSE": "LIC-7741",
}


def create_season_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["SEASON_NAME"],
        "intake_start_date": DEFAULTS["INTAKE_START_DATE"],
        "intake_end_date": DEFAULTS["INTAKE_END_DATE"],
        "spot_daily_cap": DEFAULTS["SPOT_DAILY_CAP"],
    }
    defaults.update(overrides)
    return defaults


def create_grower_payload(season_id: str, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "farm_code": DEFAULTS["FARM_CODE"],
        "legal_name": DEFAULTS["LEGAL_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(season_id: str, grower_id: str, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "grower_id": grower_id,
        "variety": DEFAULTS["VARIETY"],
        "contracted_cwt": DEFAULTS["CONTRACTED_CWT"],
        "base_price_cents_per_cwt": DEFAULTS["BASE_PRICE_CENTS_PER_CWT"],
        "grade_adjustments": dict(ZERO_GRADE_ADJUSTMENTS),
    }
    defaults.update(overrides)
    return defaults


def create_bin_payload(season_id: str, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "bin_code": DEFAULTS["BIN_CODE"],
        "capacity_cwt": DEFAULTS["BIN_CAPACITY_CWT"],
    }
    defaults.update(overrides)
    return defaults


def create_spot_lot_payload(season_id: str, grower_id: str, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "grower_id": grower_id,
        "variety": DEFAULTS["VARIETY"],
        "source": "SPOT",
        "gross_weight_lbs": DEFAULTS["GROSS_WEIGHT_LBS"],
        "tare_weight_lbs": DEFAULTS["TARE_WEIGHT_LBS"],
        "scheduled_date": DEFAULTS["SCHEDULED_DATE"],
        "moisture_pct_handheld": DEFAULTS["MOISTURE"],
        "spot_price_cents_per_cwt": DEFAULTS["SPOT_PRICE_CENTS_PER_CWT"],
    }
    defaults.update(overrides)
    return defaults


def create_contract_lot_payload(
    season_id: str,
    grower_id: str,
    contract_id: str,
    expected_contract_version: int,
    **overrides,
) -> dict:
    defaults = {
        "season_id": season_id,
        "grower_id": grower_id,
        "variety": DEFAULTS["VARIETY"],
        "source": "CONTRACT",
        "contract_id": contract_id,
        "expected_contract_version": expected_contract_version,
        "gross_weight_lbs": DEFAULTS["GROSS_WEIGHT_LBS"],
        "tare_weight_lbs": DEFAULTS["TARE_WEIGHT_LBS"],
        "scheduled_date": DEFAULTS["SCHEDULED_DATE"],
        "moisture_pct_handheld": DEFAULTS["MOISTURE"],
    }
    defaults.update(overrides)
    return defaults


def grade_lot_payload(**overrides) -> dict:
    """Laboratory grading inputs (PRD §3.4). Defaults yield grade score 1.6 -> US_NO_1."""
    defaults = {
        "moisture_pct_official": DEFAULTS["MOISTURE"],
        "foreign_matter_pct": 0.2,
        "damage_pct": 0.2,
        "broken_pct": 0.6,
    }
    defaults.update(overrides)
    return defaults


def create_drying_run_payload(season_id: str, lot_ids: list, destination_bin_id: str, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "lot_ids": list(lot_ids),
        "destination_bin_id": destination_bin_id,
    }
    defaults.update(overrides)
    return defaults


def create_mill_run_payload(season_id: str, input_bin_id: str, input_cwt: float, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "input_bin_id": input_bin_id,
        "input_cwt": input_cwt,
    }
    defaults.update(overrides)
    return defaults


def create_packaging_run_payload(season_id: str, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "line_id": "LINE_1",
        "brand_label": "MillHouse",
        "package_size_kg": 25,
        "units_planned": 100,
        "starts_at": "2026-08-20T08:00:00Z",
        "ends_at": "2026-08-20T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_byproduct_order_payload(season_id: str, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "product": "BRAN",
        "quantity_cwt": 16.00,
        "price_cents_per_cwt": DEFAULTS["BYPRODUCT_PRICE_CENTS_PER_CWT"],
        "buyer_name": DEFAULTS["BUYER_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_fumigation_event_payload(season_id: str, bin_id: str, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "bin_id": bin_id,
        "fumigant_code": DEFAULTS["FUMIGANT_CODE"],
        "applicator_license": DEFAULTS["APPLICATOR_LICENSE"],
        "started_at": "2026-08-01T00:00:00Z",
        "exposure_hours": 48,
        "aeration_hours": 24,
    }
    defaults.update(overrides)
    return defaults


def create_hold_payload(season_id: str, target_type: str, target_id: str, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "target_type": target_type,
        "target_id": target_id,
        "reason_code": "PEST_ACTIVITY",
    }
    defaults.update(overrides)
    return defaults


def create_settlement_payload(season_id: str, grower_id: str, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "grower_id": grower_id,
        "period_start_date": DEFAULTS["PERIOD_START_DATE"],
        "period_end_date": DEFAULTS["PERIOD_END_DATE"],
    }
    defaults.update(overrides)
    return defaults
