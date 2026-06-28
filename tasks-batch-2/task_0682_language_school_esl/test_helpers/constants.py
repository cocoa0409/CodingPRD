"""Domain thresholds — numeric constants from PRD calculations (§3.2, §3.6, §3.7, §3.8)."""

# Placement banding lower-bound thresholds (PRD §3.2)
PLACEMENT_BANDS = {
    "C2_MIN": 90,
    "C1_MIN": 75,
    "B2_MIN": 60,
    "B1_MIN": 45,
    "A2_MIN": 25,
}

# Add-on per-unit rates in cents (PRD §3.6)
ADDON_RATES = {
    "CONVERSATION_CLUB": 1500,
    "PRIVATE_TUTORING": 6000,
    "IMMERSION_ABROAD": 40000,
}
IMMERSION_SURCHARGE_PCT = 0.15
IMMERSION_FREE_WEEKS = 2

# Corporate discount tiers (PRD §3.6)
DISCOUNT_PCT = {
    "BRONZE": 0.00,
    "SILVER": 0.10,
    "GOLD": 0.20,
}

# Withdrawal refund tiered schedule by weeks elapsed (PRD §3.7)
WEEK_DAYS = 7
REFUND_PCT_W0 = 1.00
REFUND_PCT_W1 = 0.75
REFUND_PCT_W2_3 = 0.50
REFUND_PCT_W4_5 = 0.25

# Completion / certification (PRD §3.7)
SKILL_WEIGHT = 0.7
ATTENDANCE_WEIGHT = 0.3
MIN_PASS_ATTENDANCE = 0.70
REQUIRED_COMPLETIONS = 2
CERT_PASS_SCORE = 70

# Full course of study (PRD §3.8)
DEFAULT_REQUIRED_WEEKLY_HOURS = 18

# Pagination (PRD §2.3)
PAGINATION = {"default_limit": 10, "min_limit": 1, "max_limit": 100, "min_offset": 0}

# Logical clock default (PRD §2.4)
CLOCK_DEFAULT = "2026-04-01T00:00:00Z"
