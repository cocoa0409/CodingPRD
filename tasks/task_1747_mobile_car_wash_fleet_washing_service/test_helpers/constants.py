"""Domain thresholds — numeric constants from PRD §2.8, §2.9, §3."""

# Retail per-wash rate card in cents (PRD §3.3).
RETAIL_RATES_CENTS = {
    "SEDAN": 3500,
    "SUV_PICKUP": 4500,
    "VAN_BOXTRUCK": 7000,
    "HEAVY_FLEET": 12000,
}

# Volume discount tiers by vehicle count (PRD §3.3).
DISCOUNT_TIER_20 = 0.15
DISCOUNT_TIER_10 = 0.10
DISCOUNT_TIER_5 = 0.05
RECLAIM_SURCHARGE_PCT = 0.08

# Gross water consumption per vehicle class in gallons (PRD §2.8).
GROSS_GALLONS = {
    "SEDAN": 8.0,
    "SUV_PICKUP": 10.0,
    "VAN_BOXTRUCK": 15.0,
    "HEAVY_FLEET": 25.0,
}

# Van reclaim-system recovery fractions (PRD §2.8).
RECOVERY = {
    "NONE": 0.0,
    "BASIC": 0.60,
    "ADVANCED": 0.85,
}

# Stop planning minutes (PRD §3.4).
SHIFT_START_HOUR_UTC = 8
DRIVE_MINUTES = 20
SETUP_SMALL = 15
SETUP_MEDIUM = 25
SETUP_LARGE = 40
LOT_MEDIUM_MIN_SQFT = 10000
LOT_LARGE_MIN_SQFT = 50000
SERVICE_MINUTES = {
    "SEDAN": 20,
    "SUV_PICKUP": 25,
    "VAN_BOXTRUCK": 35,
    "HEAVY_FLEET": 50,
}

# Weather policy thresholds (PRD §3.6).
FREEZE_THRESHOLD_F = 32
RAIN_ADVISORY_PCT = 60

# Guarantee windows (PRD §3.6, §3.8).
CLAIM_WINDOW_HOURS = 72
REWASH_WINDOW_HOURS = 72
GUARANTEE_CLOSE_HOURS = 72
WEATHER_RESCHEDULE_DAYS = 14

# Quality audit (PRD §3.8).
AUDIT_PASS_SCORE = 80
CATEGORY_MAX = 20

# Damage claim class caps in cents (PRD §3.8).
CLAIM_CAPS_CENTS = {
    "SEDAN": 25000,
    "SUV_PICKUP": 30000,
    "VAN_BOXTRUCK": 40000,
    "HEAVY_FLEET": 60000,
}

# Subscription pause accounting (PRD §3.2).
PAUSE_MAX_COUNT_365D = 2
PAUSE_MAX_DAYS_365D = 90
PAUSE_MIN_DAYS = 7
PAUSE_WINDOW_DAYS = 365

# Route capacity (PRD §3.4).
ROUTE_VEHICLE_CAP = 40
TECHNICIAN_TRAVEL_BUFFER_MINUTES = 30
MIN_RECOVERY_AT_RECLAIM_SITE = 0.60

# Fleet billing (PRD §3.9).
CLAIM_CREDIT_CAP_PCT = 0.25

# Early termination (PRD §3.2).
EARLY_TERMINATION_RATE = 0.50

# Logical clock initial reading (PRD §2.5).
CLOCK_INITIAL = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "LOT_SIZE_SQFT": 8000,
    "MAX_DISCHARGE_GAL": 100,
    "VAN_TANK_GAL": 100,
    "VAN_LOAD_GAL": 96,
    "MONTHLY_MINIMUM_CENTS": 200000,
}
