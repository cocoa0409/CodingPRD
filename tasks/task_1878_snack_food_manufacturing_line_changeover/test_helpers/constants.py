"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # Oil degradation (PRD §3.4)
    "TPM_RATE_PER_1000_LBS": 2.0,
    "TEMP_DEVIATION_LIMIT_C": 5.0,
    "TEMP_FACTOR_HIGH": 1.5,
    "FILTRATION_FACTOR": 0.6,
    "TPM_HOLD_THRESHOLD": 27.0,
    "FRESH_TPM": 0.5,
    # Giveaway / compliance (PRD §3.5, §3.6)
    "MAX_REJECT_RATIO": 0.025,
    "SEASONING_BAND_PCT": 0.5,
    # Margin (PRD §3.6)
    "ABSORB_GAL_PER_1000_LBS": 1.5,
    "INGREDIENT_CENTS_PER_LB": 80,
    "SEASONING_CENTS_PER_G": 2,
    "GRAMS_PER_LB": 453.592,
    # Freshness routing (PRD §3.7)
    "DSD_MIN_DAYS": 4,
    "WH_MIN_DAYS": 10,
    # Changeover staleness (PRD §3.3)
    "VALIDATION_STALE_HOURS": 48,
}

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "OIL_CAPACITY_GALLONS": 100,
    "DECLARED_NET_WEIGHT_G": 100.0,
    "TNE_G": 1.5,
    "GIVEAWAY_MAX_PCT": 3.0,
    "SEASONING_TARGET_PCT": 4.0,
    "FRY_TARGET_TEMP_C": 180.0,
    "STANDARD_OIL_PRICE": 500,
    "CASE_REVENUE_CENTS": 4000,
    "MIN_MARGIN_CENTS": 1000,
    "SHELF_LIFE_DAYS": 30,
    "CLEANING_MINUTES_FULL_WASH": 120,
    "CLEANING_MINUTES_DRY": 30,
    "BAGS_PER_CASE": 12,
    "TRANSIT_DAYS": 2,
    "CASE_SIZE_BAGS": 12,
}
