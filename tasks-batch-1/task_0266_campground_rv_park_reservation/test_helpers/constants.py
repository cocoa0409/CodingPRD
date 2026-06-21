"""Domain thresholds — numeric constants from PRD calculations and config defaults.

Generic NON_EXISTENT_UUID comes from the framework (re-exported via the barrel).
"""

# Tiered stay-charge block sizes (PRD §3.6: a week is 7 nights, a month is 28).
WEEK_NIGHTS = 7
MONTH_NIGHTS = 28

# Loyalty discount tiers (PRD §3.6).
TIER_GOLD_CENTS = 500000
TIER_SILVER_CENTS = 200000
GOLD_PCT = 10
SILVER_PCT = 5

# Cancellation refund half-tier multiplier (PRD §3.8).
HALF_PCT = 0.50

# Park config defaults (PRD §3.1).
DEFAULT_DEPOSIT_PCT = 0.30
DEFAULT_TAX_RATE = 0.08
DEFAULT_LONG_STAY_NIGHTS_THRESHOLD = 28
DEFAULT_CHECK_IN_TIME = "15:00"
DEFAULT_CHECK_OUT_TIME = "11:00"
DEFAULT_QUIET_HOURS_START = "22:00"
DEFAULT_QUIET_HOURS_END = "07:00"
DEFAULT_TIMEZONE = "America/Denver"

# Standard RV rate plan used throughout the design indices.
STD_RV_NIGHTLY_CENTS = 5000
STD_RV_WEEKLY_CENTS = 30000
STD_RV_MONTHLY_CENTS = 100000
