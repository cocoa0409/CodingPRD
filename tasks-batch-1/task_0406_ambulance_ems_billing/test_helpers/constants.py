"""Domain thresholds — numeric constants from the PRD's calculations and reference data."""

# Base-rate billed schedule (PRD §3.3), integer cents keyed by resolved HCPCS base code.
BASE_RATE_CENTS = {
    "A0428": 45000,  # BLS non-emergency
    "A0429": 60000,  # BLS emergency
    "A0426": 65000,  # ALS1 non-emergency
    "A0427": 80000,  # ALS1 emergency
    "A0433": 110000,  # ALS2
    "A0434": 130000,  # SCT
}

MILEAGE_CENTS_PER_MILE = 1750
RURAL_BONUS_FACTOR = 1.5
RURAL_BONUS_MILE_CAP = 17

# Medicare fee-schedule baseline (PRD §3.7) used to derive allowed amounts.
MEDICARE_ALLOWED_BASE = {
    "A0428": 23000,
    "A0429": 31000,
    "A0426": 33000,
    "A0427": 41000,
    "A0433": 56000,
    "A0434": 66000,
}
MEDICARE_ALLOWED_MILEAGE_CENTS_PER_MILE = 800
MEDICARE_RURAL_BONUS_FACTOR = 1.5
MEDICAID_FACTOR = 0.80

# Charity Federal-Poverty-Level base (PRD §3.10), integer cents.
FPL_FIRST_PERSON_CENTS = 1508000
FPL_PER_ADDL_CENTS = 532000

# Default agency charity threshold (PRD §3.1).
DEFAULT_CHARITY_FPL_THRESHOLD_PCT = 200

# Default vehicle turnaround buffer in minutes (PRD §3.1 / §3.2).
DEFAULT_TURNAROUND_MINUTES = 30

# Pagination bounds (PRD §2.3).
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_LIMIT = 10
