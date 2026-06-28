"""Domain thresholds — numeric constants from the PRD's calculations and workflows."""

# Grain capacity sizing (PRD 3.2)
GALLONS_PER_PERSON_DAY = 80
IRON_HARDNESS_EQUIV = 4
REGEN_TARGET_DAYS = 6
STANDARD_TANKS = [16000, 24000, 32000, 40000, 48000, 64000]

# Regeneration demand (PRD 3.3, 3.7)
REGEN_GRACE_FACTOR = 1.25
SALT_MIN_REGEN_PCT = 20
SALT_PER_REGEN_PCT = 30
SALT_PCT_PER_BAG = 25

# Cartridge schedule windows (PRD 3.5)
CARTRIDGE_LEAD_DAYS = 14
CARTRIDGE_GRACE_DAYS = 7

# Service-gap spacing (PRD 3.4)
MIN_SERVICE_GAP_HOURS = 24

# Rental proration (PRD 3.10)
DAYS_PER_BILLING_MONTH = 30

# Early termination fee (PRD 3.8)
TIER1_MONTHS = 3
TIER2_MONTHS = 6
TIER1_RATE = 1.0
TIER2_RATE = 0.6
TIER3_RATE = 0.4
FEE_CAP_CENTS = 50000

# Claim settlement (PRD 3.9)
DEFECT_BASE_COST = {
    "VALVE_FAILURE": 18000,
    "RESIN_FOULING": 12000,
    "CONTROL_BOARD": 26000,
    "LEAK": 8000,
    "UV_BALLAST": 9000,
}
LABOR_FLAT_CENTS = 9000
GOODWILL_STEP_DAYS = 365
GOODWILL_PCT_PER_STEP = 0.05
GOODWILL_MAX = 0.30

# Coverage window per defect class in days (PRD 3.9)
COVERAGE_DAYS = {
    "VALVE_FAILURE": 1825,
    "RESIN_FOULING": 3650,
    "CONTROL_BOARD": 730,
    "LEAK": 1825,
    "UV_BALLAST": 365,
}

# Logical clock default (PRD 2.9)
CLOCK_DEFAULT = "2026-01-01T00:00:00Z"

# A syntactically valid UUID that does not correspond to any created resource.
NONEXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
