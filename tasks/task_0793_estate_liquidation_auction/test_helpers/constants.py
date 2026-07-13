"""Domain thresholds — numeric constants from the PRD's calculations."""

# Bid minimum-increment tier table (PRD §3.3).
BID_TIER_1_CEIL = 2500       # current < 2500  -> step 100
BID_TIER_2_CEIL = 10000      # 2500..<10000    -> step 250
BID_TIER_3_CEIL = 50000      # 10000..<50000   -> step 1000
BID_STEP_1 = 100
BID_STEP_2 = 250
BID_STEP_3 = 1000
BID_STEP_4 = 2500            # current >= 50000 -> step 2500

# Rates in basis points (PRD §2.5, §3).
DEFAULT_COMMISSION_BPS = 3500
DEFAULT_BUYER_PREMIUM_BPS = 1750
SALES_TAX_BPS = 800
DEFAULT_SOFT_CLOSE_SECONDS = 300

# Buyer suspension threshold (PRD §3.6).
SUSPEND_STRIKE_THRESHOLD = 3

# Logical clock startup default (PRD §2.6).
CLOCK_STARTUP_DEFAULT = "2026-03-01T00:00:00Z"
