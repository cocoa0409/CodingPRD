"""Domain thresholds and numeric constants from the PRD calculations (§2, §3)."""

# Logical clock default at server startup (PRD §2.4).
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"

# Demurrage (PRD §3.4 / §3.6).
PORT_FEE_PCT = 0.075

# Per-diem (PRD §3.1 / §3.7).
DEFAULT_FREE_DAYS = 4

# Overweight (PRD §3.5).
LEGAL_LIMIT_LBS = 80000

# Invoice totals (PRD §3.9).
FUEL_PCT = 0.22
MIN_CHARGE_CENTS = 50000
VOLUME_THRESHOLD_CENTS = 100000
VOLUME_DISCOUNT_PCT = 0.10

# Terminal appointment capacity (PRD §3.1).
DEFAULT_SLOT_CAPACITY = 1
