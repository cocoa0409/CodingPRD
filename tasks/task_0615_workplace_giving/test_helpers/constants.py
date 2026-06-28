"""Domain thresholds — numeric constants from the PRD calculations and configuration.

These mirror the default program configuration values and the fixed constants used in
the matching, dollars-for-doers, processing-fee, and disbursement calculations (PRD 3.1, 3.5-3.8).
"""

# Program configuration defaults (PRD 3.1).
PROGRAM_DEFAULTS = {
    "MATCH_RATIO": 0.5,
    "TIERED_MATCHING_ENABLED": False,
    "TIER_1_CEILING_CENTS": 50000,
    "TIER_1_RATE": 1.0,
    "TIER_2_RATE": 0.5,
    "ANNUAL_MATCH_CAP_CENTS": 100000,
    "DFD_RATE_CENTS_PER_HOUR": 1500,
    "DFD_ANNUAL_CAP_CENTS": 25000,
    "ROUNDUP_ENABLED": False,
    "PROCESSING_FEE_TIER_THRESHOLD_CENTS": 5000,
    "PROCESSING_FEE_LOW_RATE": 0.02,
    "PROCESSING_FEE_HIGH_RATE": 0.03,
    "DISBURSEMENT_ADMIN_FEE_RATE": 0.025,
}

# Fixed calculation constants (PRD 3.5, 3.7, 3.5 payroll ceiling).
ROUNDUP_DOLLAR_CENTS = 100
MINUTES_PER_HOUR = 60
MAX_DEDUCTION_FRACTION = 0.20

# Charity vetting bound (PRD 3.3): re-entry to review allowed only while review_rounds < 3.
MAX_REVIEW_ROUNDS = 3

# Standard test windows. The default logical clock is 2026-01-01T00:00:00Z (PRD 2.7),
# so a campaign/schedule spanning the whole tax year contains the default clock.
DEFAULT_TAX_YEAR = 2026
YEAR_WINDOW_START = "2026-01-01T00:00:00Z"
YEAR_WINDOW_END = "2027-01-01T00:00:00Z"
DEFAULT_CLOCK = "2026-01-01T00:00:00Z"

# A salary that yields a huge deduction ceiling so the ceiling never fires unintentionally.
HIGH_SALARY_CENTS = 120000000
DEFAULT_SALARY_CENTS = 12000000
