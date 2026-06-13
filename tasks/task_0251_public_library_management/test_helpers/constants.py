"""Domain thresholds — numeric constants from the PRD's calculations and policy defaults.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Branch policy defaults (PRD §3.1)
BRANCH_DEFAULTS = {
    "fine_free": False,
    "daily_fine_cents": 25,
    "max_fine_cents": 1000,
    "grace_days": 1,
    "loan_period_days": 21,
    "block_threshold_cents": 1000,
    "reservation_buffer_minutes": 15,
}

# Patron defaults (PRD §3.1)
PATRON_DEFAULTS = {
    "patron_type": "ADULT",
    "checkout_limit": 20,
    "hold_limit": 10,
}

# Title / Copy defaults (PRD §3.2)
TITLE_DEFAULT_REPLACEMENT_CENTS = 3000
COPY_DEFAULT_CONDITION_FACTOR = 1.0

# Loan / renewal (PRD §3.3)
MAX_RENEWALS = 2

# Replacement-charge constants (PRD §3.5)
ANNUAL_DEPRECIATION_PCT = 0.10
MAX_DEPRECIATION_PCT = 0.80
PROCESSING_FEE_PCT = 0.10

# Account-summary goodwill tier (PRD §3.1)
GOODWILL_TIER_CENTS = 2000
GOODWILL_WAIVER_CENTS = 200

# License pool (PRD §3.9)
LICENSE_POOL_DEFAULT_TERM_DAYS = 14

# ILL (PRD §3.8)
ILL_DEFAULT_LENDING_FEE_CENTS = 500

# Pagination (PRD §2.3)
PAGINATION = {"limit_default": 10, "limit_min": 1, "limit_max": 100, "offset_default": 0}
