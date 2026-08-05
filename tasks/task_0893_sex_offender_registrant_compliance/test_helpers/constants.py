"""Domain thresholds — numeric constants from PRD calculations."""

# Tier scoring (PRD 3.2)
TIER_SCORE = {
    "CLASS_A_BASE": 30,
    "CLASS_B_BASE": 20,
    "CLASS_C_BASE": 10,
    "AGG_BONUS": 10,
    "MINOR_MULT": 1.5,
    "PRIOR_BONUS_PER": 5,
    "T2_MIN": 30,
    "T3_MIN": 60,
}

VERIFICATION_INTERVAL_DAYS = {
    "TIER_1": 365,
    "TIER_2": 180,
    "TIER_3": 90,
}

# Flag severity / base points (PRD 3.5)
FLAG_BASE_POINTS = {
    "MINOR": 5,
    "MAJOR": 15,
    "CRITICAL": 40,
}

# Risk scoring / decay (PRD 3.5)
RISK = {
    "DECAY_PER_DAY": 0.01,
    "DECAY_FLOOR": 0.5,
    "DELINQUENT_THRESHOLD": 15,
}

# Notification (PRD 3.7)
NOTIFICATION_RADIUS = {
    "TIER_1": 0,
    "TIER_2": 500,
    "TIER_3": 1500,
}
NOTIFICATION_TIER_MULT = {
    "TIER_1": 0,
    "TIER_2": 3,
    "TIER_3": 10,
}

# Deregistration eligibility (PRD 3.8)
DEREGISTRATION = {
    "TIER1_MIN_YEARS": 10,
    "TIER2_MIN_YEARS": 25,
    "TIER3_MIN_YEARS": 999,
    "ADJ_MAX": 30,
}

# Defaults
DEFAULT_VERIFICATION_GRACE_DAYS = 3
DEFAULT_EST_HOUSEHOLDS = 100
DEFAULT_BUFFER_METERS = 100
TRAVEL_OVERDUE_GRACE_DAYS = 2

# Server startup logical-clock default (PRD 2.5)
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"
