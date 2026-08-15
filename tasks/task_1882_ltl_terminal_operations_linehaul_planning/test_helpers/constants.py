"""Domain thresholds and rate tables from the PRD (§2.5-§2.9, §3.2, §3.4, §3.6-§3.8)."""

# Freight rating (PRD §3.2, §3.4)
DIM_DIVISOR = 194
FUEL_SURCHARGE_PCT = 0.22
CLASS_RATE_CENTS = {
    "CLASS_50": 1800,
    "CLASS_55": 2000,
    "CLASS_60": 2150,
    "CLASS_65": 2350,
    "CLASS_70": 2500,
    "CLASS_85": 2900,
    "CLASS_100": 3400,
    "CLASS_125": 4100,
}
ACCESSORIAL_RATE_CENTS = {
    "LIFTGATE": 7500,
    "NOTIFY": 3500,
    "RESIDENTIAL": 9000,
    "INSIDE": 12000,
}

# OS&D capped liability (PRD §3.8)
LIABILITY_PER_LB_CENTS = {
    "CLASS_50": 150,
    "CLASS_55": 200,
    "CLASS_60": 250,
    "CLASS_65": 300,
    "CLASS_70": 350,
    "CLASS_85": 450,
    "CLASS_100": 600,
    "CLASS_125": 800,
}
FREIGHT_MULTIPLE_CAP = 10

# Trailer readiness gate (PRD §2.7, §3.5)
MIN_UTILIZATION_PCT = 60.0

# Relay connect buffer in minutes (PRD §3.6)
MIN_CONNECT_MINUTES = 45

# Service standard (PRD §3.1, §3.7)
ON_TIME_TARGET_PCT = 95.0
SERVICE_DAYS = {"STANDARD": 3, "EXPEDITED": 2, "GUARANTEED": 1}

# Logical clock startup value (PRD §2.9)
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "TERMINAL_CODE": "CHI",
    "TERMINAL_NAME": "Chicago",
    "DOCK_DOORS": 12,
    "ROUTE_DATE": "2026-08-01",
    "DRIVER_ID": "DRV-7",
    "SHIFT_START_MINUTE": 480,
    "SHIFT_END_MINUTE": 1020,
    "TRAILER_MAX_WEIGHT_LBS": 40000,
    "TRAILER_MAX_CUBE_CUFT": 3500,
}
