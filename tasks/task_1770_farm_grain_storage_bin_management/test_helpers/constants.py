"""Domain thresholds and numeric constants from PRD calculations."""

# Provisional / settlement shrink
SHRINK_FACTOR_PCT_PER_POINT = 1.35
STANDARD_MOISTURE_PCT = {"CORN": 15.0, "SOYBEAN": 13.0, "WHEAT": 13.5}

# Spoilage risk score
TEMP_EXCURSION_F = 10.0
HOTSPOT_DELTA_F = 30.0
HOTSPOT_ABS_F = 110.0
STALE_DAYS_FULL = 30
SCORE_WATCH = 40.0
SCORE_ALERT = 70.0

# Fumigation restricted-entry intervals (hours)
REI_HOURS = {"PHOSPHINE": 72, "SULFURYL_FLUORIDE": 24}

# Settlement fee tiers (cents)
TIER1_FLOOR_CENTS = 200_000
TIER2_FLOOR_CENTS = 500_000

# Contract fulfillment
UNDER_DELIVERY_TOLERANCE_PCT = 2.0  # contract fulfills at >= 98% delivered

# Monthly assessment
INVISIBLE_LOSS_MONTHLY_PCT = 0.20

# Carry analysis
ANNUAL_INTEREST_PCT = 6.0

# Logical clock
SERVER_START_UTC = "2026-08-01T00:00:00Z"

# Common datetimes used across fixtures
FILL_2026_08_01 = "2026-08-01T00:00:00Z"
