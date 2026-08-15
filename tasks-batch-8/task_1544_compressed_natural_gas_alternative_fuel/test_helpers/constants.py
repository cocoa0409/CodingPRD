"""Domain thresholds and numeric constants from PRD §2.5-§2.7 and §3."""

# GGE conversion (PRD §2.6): kilograms per gasoline-gallon-equivalent for CNG.
GGE_KG = 2.567

# Calibration (PRD §3.5): abs error at most 0.50% passes; due 90 days out.
CALIBRATION_TOLERANCE_PCT = 0.50
CALIBRATION_INTERVAL_DAYS = 90

# Maintenance window turnaround buffer (PRD §3.6).
TURNAROUND_HOURS = 2

# Settlement tier cap: one-tenth of committed_monthly_gge (PRD §3.8).
SHORTFALL_TIER1_CAP_PCT = 0.10

# Tax credit rates (PRD §3.9): cents per GGE.
CNG_CREDIT_CENTS_PER_GGE = 50
RNG_CREDIT_CENTS_PER_GGE = 100

# Hold timeout sweep (PRD §2.5).
HOLD_TIMEOUT_MINUTES = 30

# Logical clock startup default (PRD §2.5).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Inspection recurrence intervals in days (PRD §3.7).
INSPECTION_INTERVAL_DAYS = {
    "ANNUAL_COMPREHENSIVE": 365,
    "ODORIZATION_CHECK": 90,
    "PRESSURE_VESSEL": 730,
}

TEST_DEFAULTS = {
    "STATION_NAME": "Test Station",
    "ACCESS_MODE": "DUAL",
    "BACKUP_CAPACITY_GGE": 5000,
    "COMPRESSOR_CODE": "CMP-1",
    "CAPACITY_SCF_PER_MINUTE": 120,
    "DISPENSER_CODE": "DSP-C",
    "FUEL_TYPE": "CNG",
    "PRICE_PER_GGE_CENTS": 289,
    "POLICY_EFFECTIVE_FROM": "2026-01-01T00:00:00Z",
    "POLICY_EFFECTIVE_TO": "2027-01-01T00:00:00Z",
    "CREDIT_LIMIT_CENTS": 1000000,
    "DAILY_GGE_LIMIT": 500.0,
    "CONTRACT_COMMITTED_GGE": 100.0,
    "CONTRACT_PRICE_CENTS": 275,
    "SHORTFALL_TIER1_RATE": 30,
    "SHORTFALL_TIER2_RATE": 55,
}
