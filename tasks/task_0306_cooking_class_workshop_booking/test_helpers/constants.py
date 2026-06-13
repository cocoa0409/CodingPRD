"""Domain thresholds — numeric constants drawn from the PRD calculations (§3).

Monetary amounts are integer cents.
"""

# Per-seat skill surcharge by template skill_level (PRD §3.5).
SKILL_SURCHARGE = {
    "BEGINNER": 0,
    "INTERMEDIATE": 500,
    "ADVANCED": 1200,
    "PROFESSIONAL": 2500,
}

# Group-size discount percentage tiers keyed on seats_requested (PRD §3.5).
# <=2 -> 0%, 3-5 -> 5%, 6-9 -> 10%, >=10 -> 15%.
GROUP_DISCOUNT_TIERS = {
    "TIER_0_MAX_SEATS": 2,
    "TIER_5_MAX_SEATS": 5,
    "TIER_10_MAX_SEATS": 9,
    "PCT_TIER_0": 0.00,
    "PCT_TIER_5": 0.05,
    "PCT_TIER_10": 0.10,
    "PCT_TIER_15": 0.15,
}

# Cancellation refund tiers keyed on hours before start_at (PRD §3.7).
REFUND_TIERS = {
    "HOURS_100PCT": 168,
    "HOURS_75PCT": 72,
    "HOURS_50PCT": 24,
    "PCT_100": 1.00,
    "PCT_75": 0.75,
    "PCT_50": 0.50,
    "PCT_0": 0.00,
}
CANCELLATION_FEE_CENTS = 300

# Reliability scoring (PRD §3.2).
RELIABILITY = {
    "START_SCORE": 100,
    "NO_SHOW_PENALTY": 25,
    "LATE_CANCEL_PENALTY": 10,
    "BLOCK_THRESHOLD": 40,
}

# 24-hour late-cancel window (PRD §3.7).
LATE_CANCEL_WINDOW_HOURS = 24

# Cadence intervals in days (PRD §3.3) — fixed-length, not calendar months.
CADENCE_DAYS = {
    "WEEKLY": 7,
    "BIWEEKLY": 14,
    "MONTHLY": 28,
}

# Convenient defaults used by factories / fixtures.
TEST_DEFAULTS = {
    "BASE_PRICE_CENTS": 5000,
    "DEFAULT_CAPACITY": 4,
    "STATION_FIXED_COST_CENTS": 1000,
    "PREP_MINUTES": 0,
    "CLEANUP_MINUTES": 0,
}
