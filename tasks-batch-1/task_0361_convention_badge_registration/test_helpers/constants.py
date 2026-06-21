"""Domain thresholds and numeric constants from the PRD's calculation rules.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Group-discount tiered breakpoint schedule (PRD §3.3).
GROUP_MIN_QTY = 5
FEE_RATE = 0.03
FEE_CAP_CENTS = 5000

# Group-discount percentages keyed to total badge quantity (PRD §3.3).
GROUP_DISCOUNT_TIERS = {
    50: 0.150,
    25: 0.125,
    10: 0.100,
    5: 0.050,
}

# Refund penalty schedule (PRD §3.4).
PENALTY_FREE_DAYS = 30          # 0% when MORE than 30 days remain
PENALTY_QUARTER_MIN_DAYS = 8    # 25% when at least 8 (and <= 30) days remain
PENALTY_HALF_MIN_DAYS = 1       # 50% when at least 1 (and < 8) day remains
# 100% on the day of the event or after (zero or fewer days remain)
SECONDS_PER_DAY = 86400

# Booth zone daily rates in whole cents (PRD §3.7).
ZONE_DAILY_RATE = {
    "STANDARD": 50000,
    "PREMIUM": 120000,
    "ENDCAP": 200000,
}

# Lottery / waitlist priority scoring (PRD §3.8 / §3.6).
LOYALTY_POINTS = {
    "NONE": 0,
    "SILVER": 100,
    "GOLD": 200,
    "PLATINUM": 300,
}
EARLY_WINDOW_HOURS = 24
EARLY_BIRD_BONUS = 50
GROUP_FACTOR_PER_HEAD = 5
GROUP_FACTOR_CAP = 60

# On-site window (PRD §3.5 / §3.7).
PICKUP_WINDOW_HOURS = 48

# Badge transfer limit (PRD §3.5).
MAX_TRANSFERS = 2

# Default convention dates reused across fixtures.
DEFAULT_EVENT_START = "2026-09-01T00:00:00Z"
DEFAULT_EVENT_END = "2026-09-03T23:59:59Z"
DEFAULT_LOTTERY_OPEN = "2026-06-01T00:00:00Z"
