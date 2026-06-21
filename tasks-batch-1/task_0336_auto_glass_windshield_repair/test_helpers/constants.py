"""Domain thresholds — numeric constants from PRD calculations."""

# repair_vs_replace_decision thresholds (PRD 3.2)
DAMAGE_THRESHOLDS = {
    "CRACK_REPAIRABLE_LIMIT_MM": 150,   # crack > 150 -> REPLACE (strictly greater)
    "EDGE_SAFE_MARGIN_MM": 12,          # edge < 12 -> REPLACE (strictly less)
    "MAX_REPAIRABLE_CHIPS": 3,          # chips > 3 -> REPLACE (strictly greater)
}

# price_quote constants (PRD 3.3)
PRICE = {
    "REPAIR_BASE_CENTS": 8900,
    "REPLACE_BASE_CENTS": 32500,
    "ADAS_RECALIBRATION_FEE_CENTS": 19900,
    "SHOP_FEE_PCT": 0.085,
}

# Pre-computed quote totals (PRD 3.3 worked variants)
QUOTE_TOTALS = {
    "REPAIR": 9657,            # 8900 + round_half_up(8900*0.085=756.5 -> 757)
    "REPLACE_ADAS": 56854,     # 52400 + round_half_up(52400*0.085=4454 -> 4454)
    "REPLACE_NON_ADAS": 35263, # 32500 + round_half_up(32500*0.085=2762.5 -> 2763)
}

# schedule_trip_fee constants (PRD 3.4)
TRIP_FEE = {
    "SHOP_HOME_STATE": "CA",
    "LOCAL_TRIP_PCT": 0.04,
    "OUT_OF_STATE_TRIP_PCT": 0.09,
}

# safe_drive_away_time constants (PRD 3.5)
CURE = {
    "WARM_THRESHOLD_C": 24,
    "COLD_THRESHOLD_C": 4,
    "WARM_CURE_MIN": 60,
    "MILD_CURE_MIN": 120,
    "COLD_CURE_MIN": 240,
    "DRY_HUMIDITY_PCT": 15,
    "DRY_PENALTY_MIN": 30,
    "POSTED_ESTIMATE_MIN": 270,  # worst band: COLD 240 + DRY 30
}

# refund_amount constant (PRD 3.7)
REFUND = {
    "RESTOCK_PCT": 0.15,
}

# CALIBRATION bay clearance buffer (PRD 3.6)
CALIBRATION_BAY_BUFFER_MIN = 15
