"""Domain thresholds — numeric constants from PRD calculations and timing rules."""

THRESHOLDS = {
    # Nonaccrual delinquency threshold (PRD §3.1): nonaccrual when days_past_due >= 90
    "NONACCRUAL_DPD": 90,
    # Appraisal staleness ceiling (PRD §3.5): staleness_days <= 365
    "STALE_APPRAISAL_DAYS": 365,
    # Cumulative forgiveness ceiling (PRD §3.3): 25% of original principal, inclusive
    "FORGIVENESS_CAP_BPS": 2500,
    # Basis-point denominator
    "BPS_DENOM": 10000,
    # CECL basis-point-squared denominator
    "BPS_SQUARED_DENOM": 100000000,
    # WATERFALL costs tier: ten percent of the recovery amount
    "COST_TIER_BPS": 1000,
    # Months per year for the TDR_DCF monthly discount rate
    "MONTHS_PER_YEAR": 12,
    # Cure requirement on a RETURN_TO_PERFORMING close (PRD §3.9): days_past_due < 60
    "CURE_DPD_LIMIT": 60,
    # Downgrade-trigger entry rating floor (PRD §3.2): risk_rating_at_entry >= 6
    "DOWNGRADE_ENTRY_MIN_RATING": 6,
}

TEST_DEFAULTS = {
    "ORIGINAL_PRINCIPAL": 50_000_000,
    "RATE_BPS": 1000,
    "DAYS_PAST_DUE": 65,
    "CLOCK_DEFAULT": "2026-08-01T00:00:00Z",
}
