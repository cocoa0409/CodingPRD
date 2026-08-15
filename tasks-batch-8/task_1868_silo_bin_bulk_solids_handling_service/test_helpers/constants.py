"""Domain thresholds and rate constants (PRD §3.4, §3.6, §3.7, §3.8, §3.9)."""

# Atmosphere pass band for permit activation / resume / monitoring (PRD §3.8)
O2_MIN_PCT = 19.5
O2_MAX_PCT = 23.5
COMBUSTIBLE_MAX_PCT_LEL = 10.0

# Vessel downtime buffer, in hours (PRD §3.7)
VESSEL_DOWNTIME_BUFFER_HOURS = 2

# Per-crew-hour labor rates in integer cents, keyed by job_type (PRD §3.6 / §3.9)
BASE_RATE_CENTS_PER_CREW_HOUR = {
    "DIAGNOSIS": 9500,
    "CLEANOUT": 14500,
    "INSPECTION": 11000,
    "RETROFIT_AERATION": 22000,
    "RETROFIT_VIBRATOR": 18000,
}

# Emergency multiplier applied to estimates when the vessel is FLOW_IMPAIRED (PRD §3.6)
EMERGENCY_MULT = 1.5

# Invoice constants (PRD §3.9)
MILEAGE_RATE_CENTS_PER_MILE = 331.7
DISPOSAL_RATE_CENTS_PER_TON = 3653.92
TAX_RATE_PCT = 6.0

# Site defaults (PRD §3.1)
DEFAULT_CAPITAL_THRESHOLD_CENTS = 500000
DEFAULT_CONTRACT_DISCOUNT_PCT = 0

# Vessel defaults (PRD §3.1)
DEFAULT_TARGET_FILL_PCT = 90
DEFAULT_COVER_DAYS = 7
DEFAULT_USAGE_TONS = 1.0
DEFAULT_MOISTURE_LIMIT_PCT = 12.0
DEFAULT_TOLERANCE_PCT = 0.25

# Logical clock startup default (PRD §2.11)
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Canonical future window used by scheduling tests (strictly after the startup clock)
FUTURE_WINDOW_START = "2026-08-10T09:00:00Z"
FUTURE_WINDOW_END = "2026-08-10T17:00:00Z"
