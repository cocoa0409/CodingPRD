"""Domain thresholds — numeric constants from the PRD media-value and billing rules."""

# Media-value calculation (PRD §3.9)
OUTLET_TIER_UNITS = {
    "NATIONAL": 500000,
    "REGIONAL": 200000,
    "TRADE": 80000,
    "BLOG": 20000,
}  # base units, already in cents

SENTIMENT_WEIGHT = {
    "POSITIVE": 1.0,
    "NEUTRAL": 0.5,
    "NEGATIVE": 0.25,
}

PROMINENCE_WEIGHT = {
    "FEATURE": 1.0,
    "MENTION": 0.6,
    "PASSING": 0.3,
}

ACCOUNT_TIER_MULT = {
    "STANDARD": 1.0,
    "PREMIUM": 1.25,
    "ENTERPRISE": 1.5,
}

REACH_CAP = 3.0
ESTIMATED_HAIRCUT = 0.8

# Campaign ROI (PRD §3.10)
ROI_FLOOR_CENTS = 100000

# Logical clock startup default (PRD §2.4)
CLOCK_DEFAULT = "2026-03-01T00:00:00Z"

# Pagination defaults (PRD §2.3)
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
MIN_LIMIT = 1
DEFAULT_OFFSET = 0
