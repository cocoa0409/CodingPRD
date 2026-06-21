"""Domain thresholds — numeric constants from PRD calculations and workflows."""

# Bot-detection risk scoring (PRD §3.1)
BOT_RISK = {
    "DEVICE_SHARE_WEIGHT": 20,
    "DEVICE_SHARE_CAP": 60,
    "VELOCITY_WINDOW_SECONDS": 3600,
    "VELOCITY_FREE": 2,
    "VELOCITY_WEIGHT": 15,
    "VELOCITY_CAP": 30,
    "EMAIL_PLUS_PENALTY": 25,
    "BOT_FLAG_THRESHOLD": 70,
}

# Dynamic pricing demand bands (PRD §3.4)
PRICING = {
    "BAND1_RATIO": 0.50,
    "BAND2_RATIO": 0.80,
    "BAND1_BPS": 1500,
    "BAND2_BPS": 3000,
    "SERVICE_FEE_BPS": 1200,
}

# Refund policy (PRD §3.4)
REFUND = {
    "LOYALTY_THRESHOLD": 3,
    "STANDARD_REFUND_BPS": 9000,
}

# Queue / offer window (PRD §3.3)
QUEUE = {
    "OFFER_WINDOW_SECONDS": 120,
    "MAX_PER_FAN": 6,
}

# Defaults used to build well-formed payloads.
TEST_DEFAULTS = {
    "FACE_VALUE_CENTS": 10000,
    "VENUE_CAPACITY": 100,
    "PRESALE_CODE": "S",
    "RESALE_CAP_PCT": 110,
    "TIER_ALLOCATION": 50,
    "BASE_MULTIPLIER_BPS": 10000,
}
