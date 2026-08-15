"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    # Canonical tenant requirement (PRD §3.1 intake fields)
    "TENANT_NAME": "Acme Distribution",
    "USE_TYPE": "DISTRIBUTION",
    "MIN_SF": 90000,
    "MAX_SF": 120000,
    "MIN_CLEAR_HEIGHT_FT": 32,
    "MIN_DOCK_DOORS": 16,
    "MIN_POWER_AMPS": 3000,
    "MIN_YARD_DEPTH_FT": 150,
    "TARGET_SUBMARKET": "Inland Empire",
    "REQUIRED_DELIVERY_DATE": "2027-01-01T00:00:00Z",
    # Canonical building site
    "SITE_NAME": "Ridge Logistics Center",
    "SUBMARKET": "Inland Empire",
    "PARCEL_TYPE": "EXISTING",
    "TOTAL_SF": 200000,
    "CLEAR_HEIGHT_FT": 36,
    "DOCK_DOORS": 20,
    "POWER_AMPS": 4000,
    "YARD_DEPTH_FT": 200,
    "ZONING": "M-1",
    "ENV_PHASE": "PHASE_I_COMPLETE",
    "ASKING_RATE_PSF": 6.00,
    # Canonical land-bank parcel
    "LAND_SITE_NAME": "Victorville Land Bank",
    "LAND_SUBMARKET": "High Desert",
    "LAND_TOTAL_SF": 500000,
    "LAND_ASKING_RATE_PSF": 2.00,
    # Canonical tour window
    "TOUR_START": "2026-08-10T10:00:00Z",
    "TOUR_END": "2026-08-10T11:00:00Z",
    # Canonical LOI economics (5yr / 100000 SF / 8.00 / 10.00 TI / 6 free / 3% esc)
    "TERM_YEARS": 5,
    "LEASED_SF": 100000,
    "BASE_RATE_PSF": 8.00,
    "TI_ALLOWANCE_PSF": 10.00,
    "FREE_RENT_MONTHS": 6,
    "ESCALATION_PCT": 0.03,
    # BTS pricing inputs
    "HARD_COST_TOTAL": 10000000,
    "SOFT_COST_TOTAL": 2000000,
    "CONTINGENCY_PCT": 0.05,
    "PRICING_METHOD": "YIELD_ON_COST",
    # Expansion option window
    "OPTION_SF": 100000,
    "WINDOW_OPEN": "2026-09-01T00:00:00Z",
    "WINDOW_CLOSE": "2026-12-01T00:00:00Z",
    # Milestone
    "PLANNED_DATE": "2027-03-01T00:00:00Z",
}


def create_requirement_payload(**overrides) -> dict:
    defaults = {
        "tenant_name": DEFAULTS["TENANT_NAME"],
        "use_type": DEFAULTS["USE_TYPE"],
        "min_sf": DEFAULTS["MIN_SF"],
        "max_sf": DEFAULTS["MAX_SF"],
        "min_clear_height_ft": DEFAULTS["MIN_CLEAR_HEIGHT_FT"],
        "min_dock_doors": DEFAULTS["MIN_DOCK_DOORS"],
        "min_power_amps": DEFAULTS["MIN_POWER_AMPS"],
        "min_yard_depth_ft": DEFAULTS["MIN_YARD_DEPTH_FT"],
        "target_submarket": DEFAULTS["TARGET_SUBMARKET"],
        "required_delivery_date": DEFAULTS["REQUIRED_DELIVERY_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_site_payload(**overrides) -> dict:
    defaults = {
        "site_name": DEFAULTS["SITE_NAME"],
        "submarket": DEFAULTS["SUBMARKET"],
        "parcel_type": DEFAULTS["PARCEL_TYPE"],
        "total_sf": DEFAULTS["TOTAL_SF"],
        "clear_height_ft": DEFAULTS["CLEAR_HEIGHT_FT"],
        "dock_doors": DEFAULTS["DOCK_DOORS"],
        "power_amps": DEFAULTS["POWER_AMPS"],
        "yard_depth_ft": DEFAULTS["YARD_DEPTH_FT"],
        "zoning_designation": DEFAULTS["ZONING"],
        "environmental_phase": DEFAULTS["ENV_PHASE"],
        "asking_rate_psf": DEFAULTS["ASKING_RATE_PSF"],
    }
    defaults.update(overrides)
    return defaults


def create_land_site_payload(**overrides) -> dict:
    defaults = {
        "site_name": DEFAULTS["LAND_SITE_NAME"],
        "submarket": DEFAULTS["LAND_SUBMARKET"],
        "parcel_type": "LAND_BANK",
        "total_sf": DEFAULTS["LAND_TOTAL_SF"],
        "clear_height_ft": 0,
        "dock_doors": 0,
        "power_amps": 0,
        "yard_depth_ft": 0,
        "zoning_designation": DEFAULTS["ZONING"],
        "environmental_phase": DEFAULTS["ENV_PHASE"],
        "asking_rate_psf": DEFAULTS["LAND_ASKING_RATE_PSF"],
    }
    defaults.update(overrides)
    return defaults


def create_tour_payload(site_id, requirement_id, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "requirement_id": requirement_id,
        "start_at": DEFAULTS["TOUR_START"],
        "end_at": DEFAULTS["TOUR_END"],
    }
    defaults.update(overrides)
    return defaults


def create_loi_payload(requirement_id, site_id, **overrides) -> dict:
    defaults = {
        "requirement_id": requirement_id,
        "site_id": site_id,
        "term_years": DEFAULTS["TERM_YEARS"],
        "leased_sf": DEFAULTS["LEASED_SF"],
        "base_rate_psf": DEFAULTS["BASE_RATE_PSF"],
        "ti_allowance_psf": DEFAULTS["TI_ALLOWANCE_PSF"],
        "free_rent_months": DEFAULTS["FREE_RENT_MONTHS"],
        "escalation_pct": DEFAULTS["ESCALATION_PCT"],
    }
    defaults.update(overrides)
    return defaults


def submit_loi_payload(expected_loi_version, **overrides) -> dict:
    defaults = {"expected_loi_version": expected_loi_version}
    defaults.update(overrides)
    return defaults


def counter_loi_payload(expected_loi_version, **overrides) -> dict:
    defaults = {
        "expected_loi_version": expected_loi_version,
        "base_rate_psf": 7.50,
        "ti_allowance_psf": 12.00,
        "free_rent_months": 6,
        "escalation_pct": 0.03,
    }
    defaults.update(overrides)
    return defaults


def price_plan_payload(**overrides) -> dict:
    defaults = {
        "hard_cost_total": DEFAULTS["HARD_COST_TOTAL"],
        "soft_cost_total": DEFAULTS["SOFT_COST_TOTAL"],
        "contingency_pct": DEFAULTS["CONTINGENCY_PCT"],
        "pricing_method": DEFAULTS["PRICING_METHOD"],
    }
    defaults.update(overrides)
    return defaults


def create_milestone_payload(plan_id, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "milestone_type": "SUBSTANTIAL_COMPLETION",
        "planned_date": DEFAULTS["PLANNED_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_option_payload(loi_id, land_site_id, **overrides) -> dict:
    defaults = {
        "loi_id": loi_id,
        "land_site_id": land_site_id,
        "option_sf": DEFAULTS["OPTION_SF"],
        "window_open_date": DEFAULTS["WINDOW_OPEN"],
        "window_close_date": DEFAULTS["WINDOW_CLOSE"],
    }
    defaults.update(overrides)
    return defaults


def create_review_payload(site_id, requirement_id, review_type, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "requirement_id": requirement_id,
        "review_type": review_type,
    }
    defaults.update(overrides)
    return defaults
