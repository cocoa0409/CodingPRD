"""Domain thresholds and defaults from the PRD calculations and entity defaults."""

# Documented PRD defaults for optional fields.
DEFAULTS = {
    "GROSS_UP_OCCUPANCY_PCT": 0.95,
    "PRO_RATA_DENOMINATOR": "TOTAL_RENTABLE",
    "ADMIN_FEE_PCT": 0.0,
    "ESCALATION_TYPE": "NONE",
    "ESCALATION_RATE": 0.0,
    "PCT_RENT_RATE": 0.0,
    "PCT_RENT_BREAKPOINT_CENTS": 0,
    "CONTROLLABLE_CAP_PCT": 0.0,
    "PRIOR_YEAR_CAPPED_BASE_CENTS": 0,
    "TI_ALLOWANCE_CENTS": 0,
    "ESTIMATED_CAM_CENTS_MONTHLY": 0,
    "RECOVERABILITY": "RECOVERABLE",
    "IS_VARIABLE": False,
}

# Calculation constant.
MONTHS_PER_YEAR = 12

# Pagination defaults declared by the PRD.
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}
