"""Domain thresholds — numeric constants from PRD calculation rules."""

# Feed call quantity engine (PRD §3.3)
BUNK_DELTA = {
    0: 0.75,   # a bunk score of 0 adds three quarters of a pound per head
    1: 0.25,   # a score of 1 adds a quarter pound
    2: 0.0,    # a score of 2 leaves the quantity unchanged
    3: -0.75,  # a score of 3 subtracts three quarters of a pound
}
MIN_QTY_LBS_PER_HEAD = 8.0    # clamp floor per head
MAX_QTY_LBS_PER_HEAD = 30.0   # clamp ceiling per head
LBS_PER_TON = 2000

# Yardage (PRD §3.7): cents per head-day
YARDAGE_RATE_CENTS = 45

# Provisional cost of gain (PRD §3.7): assumed average daily gain
ADG_LBS_PER_HEAD_DAY = 3.4

# Grid pricing adjustments (PRD §3.7), cents per cwt
QUALITY_PREMIUM = {
    "PRIME": 1200,
    "CHOICE": 0,
    "SELECT": -1800,
    "STANDARD": -3500,
}
YIELD_ADJUSTMENT = {
    1: 400,
    2: 200,
    3: 0,
    4: -2000,
    5: -3500,
}

# Hedging (PRD §3.6)
CONTRACT_CWT = 400        # each live-cattle contract covers 400 hundredweight
OUT_WEIGHT_FACTOR = 1.5   # projected out-weight = average in-weight x 1.5

# Claims (PRD §3.5)
MAX_APPEALS = 1

# Logical clock (PRD §2.5): fixed startup instant
STARTUP_CURRENT_UTC = "2026-08-01T00:00:00Z"
DEFAULT_LOGICAL_DATE = "2026-08-01"
