"""Domain constants from PRD calculations and configuration."""

# Standard four-key tier copay map (PRD §3.1).
STANDARD_TIER_COPAY = {"TIER_1": 1000, "TIER_2": 3500, "TIER_3": 7000, "SPECIALTY": 25000}

# Default mail-order copay multiplier (PRD §3.1: defaults to 2.0).
DEFAULT_MAIL_ORDER_MULTIPLIER = 2.0

# Default rebate clawback fraction (PRD §3.2: defaults to 1.0).
DEFAULT_CLAWBACK_PCT = 1.0

# 30-day-equivalent fill multipliers (PRD §3.5 / §3.7).
GROSS_COST_90DAY_MULTIPLIER = 3
REBATE_90DAY_FILL_EQUIV = 3

# Default never-set clock instant (PRD §2.8).
EPOCH_UTC = "1970-01-01T00:00:00.000Z"
