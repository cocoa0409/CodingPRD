"""Domain thresholds — numeric constants from the PRD's business rules."""

# Logical clock startup default (PRD section 2.5)
CLOCK_START_ISO = "2026-08-01T00:00:00Z"

# Cooperative policy defaults (PRD section 3.1)
POLICY_DEFAULTS = {
    "FLIP_TAX_POLICY": "GROSS_PERCENT",
    "FLIP_TAX_PERCENT_BPS": 200,
    "FLIP_TAX_PER_SHARE_CENTS": 50000,
    "SUBLET_POLICY_YEARS_MAX": 2,
    "SUBLET_POLICY_GAP_YEARS": 1,
    "ARREARS_LATE_FEE_FLAT_CENTS": 5000,
    "ARREARS_INTEREST_RATE_BPS": 600,
    "ARREARS_GRACE_DAYS": 10,
    "ARREARS_TERMINATION_THRESHOLD_CENTS": 1000000,
    "ANNUAL_MEETING_QUORUM_PERCENT_BPS": 5000,
}

# Purchase-application gates (PRD sections 3.5 / 3.6)
FINANCING_CAP_BPS = 8000            # 80% house cap on buyer financing
DTI_MAX_BPS = 2800                  # 28% buyer debt-to-income ceiling
MORTGAGE_RATE_ASSUMPTION_BPS = 700  # 7% APR mortgage estimate assumption
MONTHS_LIQUIDITY_REQUIRED = 12

# Board composition (PRD section 3.2)
BOARD_SIZE = 5
VOTES_REQUIRED = 3                  # majority of the five-seat board

# Sublet fee (PRD section 3.7)
SUBLET_FEE_RATE_BPS = 1500          # 15% of the unit's current base maintenance

# Alteration safety (PRD section 3.8)
CONTRACTOR_INSURANCE_MIN_CENTS = 100000000   # $1M liability minimum
SECURITY_DEPOSIT_MIN_CENTS = 500000          # $5,000 deposit floor
SECURITY_DEPOSIT_RATE_BPS = 500              # 5% of contractor bid

# Arrears action cure windows, in days (PRD section 3.4)
CURE_DEADLINE_DAYS = {
    "LATE_NOTICE": 30,
    "DEMAND_LETTER": 15,
    "TERMINATION_NOTICE": 10,
}

# Pagination contract (PRD section 2.3)
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MAX = 100

# Standard voter panel used when passing resolutions in fixtures
DEFAULT_VOTER_IDS = ("bm-voter-1", "bm-voter-2", "bm-voter-3")
DEFAULT_PANEL_IDS = ("bm-panel-1", "bm-panel-2")
CERTIFIER_USER_ID = "ma-certifier-1"
