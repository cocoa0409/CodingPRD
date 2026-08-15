"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "FACILITY_NAME": "Test Facility",
    "UTILITY_RATE_CENTS_PER_KWH": 12,
    "OPERATING_HOURS_PER_YEAR": 6000,
    "REPAIR_BUDGET_CENTS": 5_000_000,
    "ASSET_TAG": "C1",
    "RATED_KW": 75,
    "RATED_CFM": 400,
    "WINDOW_START": "2026-03-01",
    "WINDOW_END": "2026-03-31",
    "MEASURED_KWH": 248000,
    "MEASURED_AVG_CFM": 350.0,
    "MEASURED_PEAK_CFM": 520.0,
    "SURVEY_DATE": "2026-03-15",
    "LOCATION_DESCRIPTION": "leak",
    "CFM_LOSS": 5.0,
    "REPAIR_QUOTE_CENTS": 100000,
    "COMPONENT": "DRYER",
    "INTERVAL_HOURS": 2000,
    "BASELINE_PRESSURE_PSI": 125,
    "TARGET_PRESSURE_PSI": 100,
    "PROJECT_COST_CENTS": 50_000_000,
    "TIER": "STANDARD",
    "CONTRACT_START_DATE": "2026-08-01",
    "TERM_MONTHS": 12,
    "MONTHLY_FEE_CENTS": 400000,
    "SEVERITY": "URGENT",
    "FLEET_TAG": "A1",
    "RENTAL_RATED_CFM": 500,
    "DAILY_RATE_CENTS": 35000,
    "DEPOSIT_CENTS": 100000,
    "RENTAL_START": "2026-09-01",
    "RENTAL_END": "2026-09-05",
    "GUARANTEED_PCT": 0.90,
}


def create_facility_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["FACILITY_NAME"],
        "utility_rate_cents_per_kwh": DEFAULTS["UTILITY_RATE_CENTS_PER_KWH"],
        "operating_hours_per_year": DEFAULTS["OPERATING_HOURS_PER_YEAR"],
        "repair_budget_cents": DEFAULTS["REPAIR_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_compressor_payload(**overrides) -> dict:
    defaults = {
        "facility_id": None,
        "asset_tag": DEFAULTS["ASSET_TAG"],
        "rated_kw": DEFAULTS["RATED_KW"],
        "rated_cfm": DEFAULTS["RATED_CFM"],
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_demand_profile_payload(**overrides) -> dict:
    defaults = {
        "facility_id": None,
        "window_start_date": DEFAULTS["WINDOW_START"],
        "window_end_date": DEFAULTS["WINDOW_END"],
        "measured_kwh": DEFAULTS["MEASURED_KWH"],
        "measured_avg_cfm": DEFAULTS["MEASURED_AVG_CFM"],
        "measured_peak_cfm": DEFAULTS["MEASURED_PEAK_CFM"],
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_leak_survey_payload(**overrides) -> dict:
    defaults = {
        "facility_id": None,
        "survey_date": DEFAULTS["SURVEY_DATE"],
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_leak_tag_payload(**overrides) -> dict:
    defaults = {
        "location_description": DEFAULTS["LOCATION_DESCRIPTION"],
        "cfm_loss": DEFAULTS["CFM_LOSS"],
        "repair_quote_cents": DEFAULTS["REPAIR_QUOTE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_maintenance_schedule_payload(**overrides) -> dict:
    defaults = {
        "facility_id": None,
        "component": DEFAULTS["COMPONENT"],
        "interval_hours": DEFAULTS["INTERVAL_HOURS"],
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_retrofit_project_payload(**overrides) -> dict:
    defaults = {
        "facility_id": None,
        "baseline_pressure_psi": DEFAULTS["BASELINE_PRESSURE_PSI"],
        "target_pressure_psi": DEFAULTS["TARGET_PRESSURE_PSI"],
        "sequence_compressor_ids": [],
        "project_cost_cents": DEFAULTS["PROJECT_COST_CENTS"],
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_savings_case_payload(**overrides) -> dict:
    defaults = {
        "facility_id": None,
        "baseline_profile_id": None,
        "retrofit_project_id": None,
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_service_contract_payload(**overrides) -> dict:
    defaults = {
        "facility_id": None,
        "tier": DEFAULTS["TIER"],
        "start_date": DEFAULTS["CONTRACT_START_DATE"],
        "term_months": DEFAULTS["TERM_MONTHS"],
        "monthly_fee_cents": DEFAULTS["MONTHLY_FEE_CENTS"],
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_service_ticket_payload(**overrides) -> dict:
    defaults = {
        "facility_id": None,
        "compressor_id": None,
        "severity": DEFAULTS["SEVERITY"],
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_rental_asset_payload(**overrides) -> dict:
    defaults = {
        "fleet_tag": DEFAULTS["FLEET_TAG"],
        "rated_cfm": DEFAULTS["RENTAL_RATED_CFM"],
        "daily_rate_cents": DEFAULTS["DAILY_RATE_CENTS"],
        "deposit_cents": DEFAULTS["DEPOSIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_rental_reservation_payload(**overrides) -> dict:
    defaults = {
        "facility_id": None,
        "down_compressor_id": None,
        "start_date": DEFAULTS["RENTAL_START"],
        "end_date": DEFAULTS["RENTAL_END"],
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_guarantee_certificate_payload(**overrides) -> dict:
    defaults = {
        "facility_id": None,
        "contract_id": None,
        "savings_case_id": None,
        "guaranteed_pct": DEFAULTS["GUARANTEED_PCT"],
    }
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}
