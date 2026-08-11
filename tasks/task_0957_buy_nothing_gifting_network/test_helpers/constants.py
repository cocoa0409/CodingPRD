"""Domain thresholds — numeric constants from the PRD (§2.5, §2.8, §2.9, §2.10, §2.11, §3)."""

# Logical clock (PRD §2.5): startup default before any set_current_utc call.
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"

# Reputation (PRD §2.8)
REPUTATION = {
    "WELCOME_BONUS_POINTS": 5,
    "GIFT_COMPLETED_POINTS": 10,
    "RECEIVE_COMPLETED_POINTS": 3,
    "NO_SHOW_PENALTY_POINTS": -8,
    "STRIKE_APPLIED_MULTIPLIER": -2,
    "SETTLE_AFTER_DAYS": 7,
    "WEIGHT_FULL_MAX_DAYS": 30,
    "WEIGHT_MID_MAX_DAYS": 90,
    "WEIGHT_MID": 0.75,
    "WEIGHT_OLD": 0.5,
}

# Fairness score (PRD §2.8)
FAIRNESS = {
    "BASE": 50,
    "GIVEN_WEIGHT": 2,
    "RECEIVED_WEIGHT": -3,
    "STRIKE_WEIGHT": -10,
    "SENIORITY_BONUS": 5,
    "SENIORITY_MIN_DAYS": 180,
    "FLOOR": 0,
    "CEILING": 100,
}

# Group health + report SLA (PRD §2.9)
GROUP_HEALTH = {
    "GIFT_POINTS": 2,
    "OPEN_REPORT_PENALTY": 5,
    "OVERDUE_PENALTY": 10,
    "GREEN_MIN": 20,
    "SLA_GREEN_HOURS": 96,
    "SLA_YELLOW_HOURS": 72,
    "SLA_RED_HOURS": 48,
}

# Strikes / suspension / ban (PRD §2.10)
STRIKES = {
    "SUSPEND_THRESHOLD_POINTS": 3,
    "BAN_THRESHOLD_POINTS": 6,
    "STRIKE_TTL_DAYS": 90,
    "SUSPENSION_DAYS": 14,
}

# Offer window (PRD §3.3)
OFFER_WINDOW_HOURS = 24

# Pickup window buffer (PRD §2.11)
PICKUP_BUFFER_MINUTES = 15

# Curb-alert zone capacity (PRD §3.6)
CURB_ZONE_MAX_OVERLAP = 3

# Wishlist lifetime (PRD §3.5)
WISHLIST_LIFETIME_DAYS = 30

# Pickup negotiation (PRD §3.4)
MAX_NEGOTIATION_ROUNDS = 3

# Pagination defaults (PRD §2.3)
PAGINATION = {"DEFAULT_LIMIT": 10, "MIN_LIMIT": 1, "MAX_LIMIT": 100, "DEFAULT_OFFSET": 0}
