"""Domain thresholds — numeric constants named in PRD prose (§2.5, §3)."""

# PRD §2.5: "Before any client call, the logical clock reads exactly
# 2026-08-01T00:00:00Z"
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

THRESHOLDS = {
    # PRD §3.5 lease-rate occupancy tiers and clamp bounds
    "TIER1_MAX": 70,
    "TIER2_MAX": 85,
    "TIER3_MAX": 95,
    "TIER1_ADJ_BPS": -1000,
    "TIER2_ADJ_BPS": -500,
    "TIER3_ADJ_BPS": 0,
    "TIER4_ADJ_BPS": 500,
    "FLOOR_OF_PROPOSED_BPS": 9500,
    "CEILING_OF_MARKET_BPS": 11000,
    # PRD §3.3 zero-budget variance cap (10000% pinned)
    "ZERO_BUDGET_NONZERO_ACTUAL_BPS": 1000000,
    # PRD §3.6 LTV valuation freshness window (days)
    "LTV_VALUATION_MAX_AGE_DAYS": 270,
    # PRD §3.6 lender report due-date offset (days)
    "REPORT_DUE_DAYS_AFTER_QUARTER_END": 45,
    # PRD §3.3 reforecast cadence months and hard cap
    "REFORECAST_CADENCE_MONTHS": (4, 7, 10),
    "REFORECAST_MAX_APPLIED": 3,
    # PRD §3.7 scorecard rating boundaries
    "EXCELLENT_MIN": 85,
    "SATISFACTORY_MIN": 70,
    "WATCH_MIN": 55,
    "EXP_BPS_PER_POINT": 50,
    # PRD §3.8 decision trigger arming thresholds
    "REFI_MIN_DSCR_BPS": 14000,
    "REFI_MAX_LTV_BPS": 6000,
    "REFI_MAX_MONTHS_TO_MATURITY": 18,
    "SELL_MIN_VALUE_GAIN_BPS": 2500,
    # PRD §3.9 posture: two or more WATCH loans restrict the portfolio
    "WATCH_RESTRICTED_COUNT": 2,
}

# Budget-line category groupings (PRD §3.2 names all ten)
REVENUE_CATEGORIES = ["RENT_REVENUE", "PARKING_REVENUE", "OTHER_REVENUE"]
EXPENSE_CATEGORIES = [
    "CAM_EXPENSE", "TAX_EXPENSE", "INSURANCE_EXPENSE", "UTILITIES_EXPENSE",
    "MANAGEMENT_FEE_EXPENSE", "OTHER_OPEX",
]
NON_CAPITAL_CATEGORIES = REVENUE_CATEGORIES + EXPENSE_CATEGORIES
ALL_CATEGORIES = NON_CAPITAL_CATEGORIES + ["CAPITAL"]
