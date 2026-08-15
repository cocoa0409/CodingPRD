"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "MARKET_NAME": "Metro X",
    "STATE_CODE": "TX",
    "POPULATION": 500000,
    "INCOME_CENTS": 9000000,
    "GROWTH_BP": 300,
    "PSYCHO_INDEX": 130,
    "BASE_TARGET_STORES": 5,
    "CAPEX_BUDGET_CENTS": 2000000000,
    "MAX_RENT_PSF_CENTS": 40000,
    "PROTOTYPE_SALES_CENTS": 900000000,
    "STORE_FORMAT": "STANDARD",
    "STORE_SALES_CENTS": 1000000000,
    "SITE_ADDRESS": "5 Elm St",
    "SITE_FORMAT": "STANDARD",
    "SITE_SQFT": 10000,
    "ASKING_RENT_PSF_CENTS": 3000,
    "CAM_PSF_CENTS": 800,
    "TAX_PSF_CENTS": 400,
    "BUILD_COST_CENTS": 500000000,
    "DRIVE_TIME_MINUTES": 15,
    "TRADE_AREA_POPULATION": 50000,
    "PER_CAPITA_SPEND_CENTS": 300000,
    "CANNIBALIZATION_VARIANT": "FLAT_BAND",
    "LISTING_TYPE": "COMPETITOR",
    "BRAND_NAME": "Rival",
    "ESTIMATED_SQFT": 8000,
    "DISTANCE_MINUTES": 5,
    "VISITED_ON": "2026-08-05",
    "VISIBILITY": 80,
    "ACCESS": 90,
    "PARKING": 70,
    "COTENANCY": 85,
    "MODEL_VARIANT": "ANALOG",
    "MEMBER_NAME": "Member",
    "BALLOT": "APPROVE",
    "RENT_PSF_CENTS": 2000,
    "ESCALATION_PCT_BP": 200,
    "TERM_YEARS": 3,
    "TI_ALLOWANCE_CENTS": 500000,
    "FREE_RENT_MONTHS": 2,
    "EXCL_START": "2026-09-01",
    "EXCL_END": "2026-10-01",
    "FINAL_RENT_PSF_CENTS": 2100,
    "BUILD_START": "2026-09-01",
    "BUILD_END": "2026-10-15",
    "CREW_CODE": "CREW-1",
    "MILESTONE_TYPE": "PERMIT_SUBMITTED",
    "PLANNED_DATE": "2026-09-05",
    "ACTUAL_DATE": "2026-09-05",
    "PERIOD_INDEX": 1,
    "ACTUAL_SALES_CENTS": 100000000,
}


def create_market_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["MARKET_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "population": DEFAULTS["POPULATION"],
        "median_household_income_cents": DEFAULTS["INCOME_CENTS"],
        "population_growth_bp": DEFAULTS["GROWTH_BP"],
        "psychographic_index": DEFAULTS["PSYCHO_INDEX"],
        "base_target_stores": DEFAULTS["BASE_TARGET_STORES"],
        "annual_capex_budget_cents": DEFAULTS["CAPEX_BUDGET_CENTS"],
        "max_rent_psf_cents": DEFAULTS["MAX_RENT_PSF_CENTS"],
        "prototype_sales_cents": DEFAULTS["PROTOTYPE_SALES_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_store_payload(**overrides) -> dict:
    defaults = {
        "market_id": None,
        "store_code": "ST-1",
        "format_type": DEFAULTS["STORE_FORMAT"],
        "annual_sales_cents": DEFAULTS["STORE_SALES_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_site_payload(**overrides) -> dict:
    defaults = {
        "market_id": None,
        "address": DEFAULTS["SITE_ADDRESS"],
        "format_type": DEFAULTS["SITE_FORMAT"],
        "square_footage": DEFAULTS["SITE_SQFT"],
        "asking_rent_psf_cents": DEFAULTS["ASKING_RENT_PSF_CENTS"],
        "cam_psf_cents": DEFAULTS["CAM_PSF_CENTS"],
        "tax_psf_cents": DEFAULTS["TAX_PSF_CENTS"],
        "build_cost_cents": DEFAULTS["BUILD_COST_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_trade_area_model_payload(**overrides) -> dict:
    defaults = {
        "site_id": None,
        "drive_time_minutes": DEFAULTS["DRIVE_TIME_MINUTES"],
        "trade_area_population": DEFAULTS["TRADE_AREA_POPULATION"],
        "per_capita_spend_cents": DEFAULTS["PER_CAPITA_SPEND_CENTS"],
        "cannibalization_variant": DEFAULTS["CANNIBALIZATION_VARIANT"],
    }
    defaults.update(overrides)
    return defaults


def create_competitor_listing_payload(**overrides) -> dict:
    defaults = {
        "trade_area_model_id": None,
        "listing_type": DEFAULTS["LISTING_TYPE"],
        "brand_name": DEFAULTS["BRAND_NAME"],
        "estimated_sqft": DEFAULTS["ESTIMATED_SQFT"],
        "distance_minutes": DEFAULTS["DISTANCE_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_site_visit_payload(**overrides) -> dict:
    defaults = {
        "site_id": None,
        "visited_on": DEFAULTS["VISITED_ON"],
        "visibility_score": DEFAULTS["VISIBILITY"],
        "access_score": DEFAULTS["ACCESS"],
        "parking_score": DEFAULTS["PARKING"],
        "cotenancy_score": DEFAULTS["COTENANCY"],
    }
    defaults.update(overrides)
    return defaults


def create_sales_forecast_payload(**overrides) -> dict:
    defaults = {
        "site_id": None,
        "trade_area_model_id": None,
        "model_variant": DEFAULTS["MODEL_VARIANT"],
    }
    defaults.update(overrides)
    return defaults


def create_committee_member_payload(**overrides) -> dict:
    defaults = {"display_name": DEFAULTS["MEMBER_NAME"]}
    defaults.update(overrides)
    return defaults


def create_submit_committee_payload(**overrides) -> dict:
    defaults = {
        "sales_forecast_id": None,
        "sponsor_member_id": None,
        "expires_at": "2026-08-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_vote_payload(**overrides) -> dict:
    defaults = {
        "ballot": DEFAULTS["BALLOT"],
        "expected_review_version": None,
    }
    defaults.update(overrides)
    return defaults


def create_loi_payload(**overrides) -> dict:
    defaults = {
        "site_id": None,
        "rent_psf_cents": DEFAULTS["RENT_PSF_CENTS"],
        "escalation_pct_bp": DEFAULTS["ESCALATION_PCT_BP"],
        "term_years": DEFAULTS["TERM_YEARS"],
        "ti_allowance_cents": DEFAULTS["TI_ALLOWANCE_CENTS"],
        "free_rent_months": DEFAULTS["FREE_RENT_MONTHS"],
        "exclusivity_start_date": DEFAULTS["EXCL_START"],
        "exclusivity_end_date": DEFAULTS["EXCL_END"],
    }
    defaults.update(overrides)
    return defaults


def create_lease_payload(**overrides) -> dict:
    defaults = {
        "loi_id": None,
        "final_rent_psf_cents": DEFAULTS["FINAL_RENT_PSF_CENTS"],
        "escalation_pct_bp": DEFAULTS["ESCALATION_PCT_BP"],
        "term_years": DEFAULTS["TERM_YEARS"],
        "ti_allowance_cents": DEFAULTS["TI_ALLOWANCE_CENTS"],
        "free_rent_months": DEFAULTS["FREE_RENT_MONTHS"],
        "crew_id": None,
        "build_start_date": DEFAULTS["BUILD_START"],
        "build_end_date": DEFAULTS["BUILD_END"],
    }
    defaults.update(overrides)
    return defaults


def create_construction_crew_payload(**overrides) -> dict:
    defaults = {"crew_code": DEFAULTS["CREW_CODE"]}
    defaults.update(overrides)
    return defaults


def create_permit_milestone_payload(**overrides) -> dict:
    defaults = {
        "site_id": None,
        "milestone_type": DEFAULTS["MILESTONE_TYPE"],
        "planned_date": DEFAULTS["PLANNED_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_performance_snapshot_payload(**overrides) -> dict:
    defaults = {
        "site_id": None,
        "period_index": DEFAULTS["PERIOD_INDEX"],
        "actual_sales_cents": DEFAULTS["ACTUAL_SALES_CENTS"],
    }
    defaults.update(overrides)
    return defaults
