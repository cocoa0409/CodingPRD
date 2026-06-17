"""Domain thresholds — numeric constants from the PRD calculations (§3)."""

# Finance APR bands in basis points by credit tier (PRD §3.4).
APR_BAND = {"PRIME": 599, "STANDARD": 899, "SUBPRIME": 1499}

# Maximum loan-to-value ceilings in basis points by credit tier (PRD §3.4).
MAX_LTV_BPS = {"PRIME": 13000, "STANDARD": 12000, "SUBPRIME": 11000}

# Finance term bounds, inclusive (PRD §3.4).
TERM_MIN_MONTHS = 12
TERM_MAX_MONTHS = 240

# Flat winterization fee added to storage charge (PRD §3.10).
WINTERIZE_FEE_CENTS = 25000

# Seconds in a day for storage day-count ceiling (PRD §3.10).
SECONDS_PER_DAY = 86400
