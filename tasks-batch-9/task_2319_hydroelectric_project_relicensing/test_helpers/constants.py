"""Domain thresholds and numeric constants named by the PRD's calculations."""

# ---- PME cost estimation ---------------------------------------------------
CONTINGENCY_PCT_PRELIMINARY = 0.25
CONTINGENCY_PCT_DEFINITIVE = 0.10
ESCALATION_PCT_PER_YEAR = 0.03
AMORTIZATION_YEARS_BY_CATEGORY = {
    "FISH_PASSAGE": 30,
    "WATER_QUALITY": 20,
    "RECREATION": 15,
    "CULTURAL": 10,
}

# ---- generation impact -----------------------------------------------------
PROXY_MWH_PER_CFS_DAY = 0.048
PLANT_EFFICIENCY = 0.85
HYDRO_KW_DIVISOR = 11.8
ENERGY_PRICE_USD_PER_MWH = 42.00

# ---- settlement support tally ---------------------------------------------
SUPPORT_THRESHOLD_PCT = 66.67
MAX_NEGOTIATION_ROUNDS = 3

# ---- administrative charge tiers ------------------------------------------
ADMIN_CHARGE_TIER_LOW_PCT = 0.02
ADMIN_CHARGE_TIER_MID_PCT = 0.035
ADMIN_CHARGE_TIER_HIGH_PCT = 0.05
ADMIN_CHARGE_TIER_1_LIMIT_USD = 500000.00
ADMIN_CHARGE_TIER_2_LIMIT_USD = 2000000.00

# ---- economic feasibility -------------------------------------------------
BURDEN_RATIO_LIMIT_PCT = 15.00

# ---- statutory timeline ---------------------------------------------------
PAD_LEAD_MONTHS = 66
APPLICATION_LEAD_MONTHS = 24
TIMELINE_AT_RISK_DAYS = 180

# ---- obligation scheduling ------------------------------------------------
PREREQ_LAG_MONTHS = 6
PUBLIC_SAFETY_SIGNAGE_MONTHS = 12
EAP_EXERCISE_MONTHS = 24

# ---- water quality certification ------------------------------------------
WQC_WAIVER_MONTHS = 12

# ---- study review ---------------------------------------------------------
MAX_ADDITIONAL_STUDY_ROUNDS = 2

# ---- logical clock --------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    "SUPPORT_THRESHOLD_PCT": SUPPORT_THRESHOLD_PCT,
    "BURDEN_RATIO_LIMIT_PCT": BURDEN_RATIO_LIMIT_PCT,
    "TIMELINE_AT_RISK_DAYS": TIMELINE_AT_RISK_DAYS,
    "MAX_NEGOTIATION_ROUNDS": MAX_NEGOTIATION_ROUNDS,
    "MAX_ADDITIONAL_STUDY_ROUNDS": MAX_ADDITIONAL_STUDY_ROUNDS,
    "PAGINATION_MAX_LIMIT": 100,
    "PAGINATION_DEFAULT_LIMIT": 10,
}

TEST_DEFAULTS = {
    "INSTALLED_CAPACITY_MW": 12.0,
    "BASE_ANNUAL_GENERATION_MWH": 250000,
    "LICENSE_EXPIRATION_DATE": "2035-06-30",
    "PROJECT_NAME": "Test Reach Hydro",
    "PLAN_TITLE": "Study Plan 1",
    "SITE_CODE": "S1",
    "RIVER_MILE": 1.0,
    "CERTIFYING_AGENCY_NAME": "State DEQ",
}

# The recurring water-quality condition used across the design recipes.
STANDARD_WQC_CONDITION = {
    "measure_name": "Minimum flow release",
    "resource_category": "WATER_QUALITY",
    "capital_cost_usd": 600000.00,
    "annual_om_cost_usd": 20000.00,
    "construction_start_year": 2026,
    "implementation_months": 6,
    "flow_release_cfs": 40,
    "gross_head_ft": 60,
    "release_days": 120,
}
