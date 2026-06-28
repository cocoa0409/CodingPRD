"""Domain thresholds — numeric constants from the PRD calculations.

Generic NON_EXISTENT_UUID is re-exported from the framework via the barrel.
"""

# Instant-deposit provisional-credit cumulative ceiling (PRD §3.1): $100,000.
INSTANT_CAP_CENTS = 10_000_000

# Options suitability thresholds (PRD §3.8).
L3_MIN_NET_WORTH_CENTS = 10_000_000     # $100,000
L3_MIN_EXPERIENCE_YEARS = 3
L2_MIN_EXPERIENCE_YEARS = 2
L1_MIN_EXPERIENCE_YEARS = 1

# PFOF venue rebates in basis points (PRD §3.4).
VENUE_A_REBATE_BPS = 30
VENUE_B_REBATE_BPS = 20
VENUE_C_REBATE_BPS = 10

# Margin leverage multiplier (PRD §3.4).
MARGIN_MULTIPLIER = 2

# PDT rule (PRD §3.9).
PDT_THRESHOLD = 4
PDT_MIN_EQUITY_CENTS = 2_500_000        # $25,000.00
WINDOW_BUSINESS_DAYS = 5

# Cost-basis term boundary (PRD §3.5).
LONG_TERM_DAYS = 365

# Share precision (PRD §2.5): quantities truncated to 6 decimal places.
SHARE_PRECISION_DP = 6

# Temporal windows (PRD §3.7 / §3.9).
DIVIDEND_WINDOW_DAYS = 30
MARGIN_CURE_DAYS = 4

# Default maintenance rate for a security in basis points (PRD §3.2).
DEFAULT_MAINTENANCE_RATE_BPS = 2500

# Logical-clock startup default (PRD §2.5).
CLOCK_DEFAULT_ISO = "2026-01-01T00:00:00Z"
