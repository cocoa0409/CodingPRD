"""Domain thresholds — numeric constants from PRD calculations and validations."""

TRUST_TIER_THRESHOLDS = {
    "ANCHOR_MIN_VERIFIED": 3,
    "ANCHOR_MIN_COMPLETED": 20,
    "TRUSTED_MIN_VERIFIED": 2,
    "TRUSTED_MIN_COMPLETED": 5,
}

NO_SHOW = {
    "WINDOW_DAYS": 90,
    "SUSPENSION_THRESHOLD": 3,
}

MINUTES = {
    "MIN_PER_SESSION": 15,
    "MAX_PER_SESSION": 480,
    "STEP": 15,
    "TRAVEL_BUFFER_MINUTES": 30,
    "ADMIN_ADJUST_MIN": -4800,
    "ADMIN_ADJUST_MAX": 4800,
}

REVISION_CAP = 2

PROJECT = {
    "DEFAULT_MIN_COMPLETED_RATIO": 0.60,
}

BOOT_CLOCK = "2026-03-01T00:00:00Z"

# Reward catalogue (server-authoritative in the real system; used only in tests)
REWARD_CODES = {
    "FARMERS_MARKET_15": 15,
    "BUS_PASS_60": 60,
}
