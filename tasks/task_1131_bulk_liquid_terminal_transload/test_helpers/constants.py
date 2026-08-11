"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Logical clock (PRD §2.4): startup default, never falls back to wall time.
CLOCK_DEFAULT_ISO = "2026-05-01T00:00:00Z"

# Tank working capacity (PRD §2.6)
DEFAULT_SAFE_FILL_PCT = 0.95

# Custody volume measurement correction (PRD §3.7)
CTL_COEFF = 0.0006
REF_TEMP_F = 60
GRADE_STD_SG = {
    "GASOLINE": 0.74,
    "DIESEL": 0.85,
    "JET": 0.80,
    "ETHANOL": 0.79,
    "CRUDE": 0.87,
}

# Loss control (PRD §3.7 / §3.8)
LOSS_CONTROL_CAP_BBL = 100

# Demurrage / dwell (PRD §3.9)
FREE_HOURS_BY_MODE = {"VESSEL": 24, "RAIL": 48, "TRUCK": 4}
RATE_PER_HOUR_BY_MODE = {"VESSEL": 1200.00, "RAIL": 85.00, "TRUCK": 60.00}
LATE_GRACE_MINUTES = 30

# Tiered throughput fee (PRD §3.8)
TIER1_CAP = 50000
TIER2_CAP = 200000
TIER2_DISCOUNT = 0.90
TIER3_DISCOUNT = 0.75

# Quality sample retain (PRD §3.7)
RETAIN_DAYS = 30

# Common scenario defaults used across fixtures
DEFAULTS = {
    "LEASE_START": "2026-01-01",
    "LEASE_END": "2026-12-31",
    "PERIOD_START": "2026-01-01",
    "PERIOD_END": "2026-12-31",
    "THROUGHPUT_FEE_PER_BBL": 0.50,
    "SHORTFALL_FEE_PER_BBL": 0.50,
    "LOSS_ALLOWANCE_PCT": 0.005,
    "EXCESS_LOSS_RATE_PER_BBL": 50.00,
    "MIN_MONTHLY_THROUGHPUT_BBL": 100,
    "COMMITTED_CAPACITY_BBL": 50000,
    "ALLOCATED_BBL": 20000,
    "TANK_CAPACITY_BBL": 100000,
    "DECLARED_VOLUME_BBL": 100,
    "WINDOW_START": "2026-05-10T08:00:00Z",
    "WINDOW_END": "2026-05-10T12:00:00Z",
    "STATEMENT_PERIOD": "2026-05",
    "STATEMENT_CLOSE_CLOCK": "2026-06-01T00:00:00Z",
}
