"""Domain thresholds — numeric constants from the PRD's calculations (Section 3)."""

# Tier qualifying-segment thresholds (PRD §3.4).
TIER_THRESHOLDS = {"BASE": 0, "SILVER": 15, "GOLD": 30, "PLATINUM": 60}
TIER_RANK = {"BASE": 0, "SILVER": 1, "GOLD": 2, "PLATINUM": 3}

# Segment accrual (PRD §3.2).
FARE_CLASS_MULT = {"DISCOUNT": 0.5, "ECONOMY": 1.0, "BUSINESS": 1.5, "FIRST": 2.0}
TIER_BONUS_PCT = {"BASE": 0, "SILVER": 25, "GOLD": 50, "PLATINUM": 100}
MIN_MILE_RATE = 0.5

# Award pricing (PRD §3.5).
AWARD_CHART = {"ECONOMY": 25000, "BUSINESS": 60000, "FIRST": 100000}
COMPANION_ADDON_PCT = 50

# Upgrade priority (PRD §3.8).
FARE_WEIGHT = {"DISCOUNT": 0, "ECONOMY": 10, "BUSINESS": 20, "FIRST": 30}

# Expiry window (PRD §3.7).
EXPIRY_MONTHS = 18
