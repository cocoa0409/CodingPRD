"""Domain thresholds — numeric constants from the PRD calculations (Section 3)."""

# Jurisdiction statutory defaults (PRD 3.1).
JURISDICTION_DEFAULTS = {
    "INTEREST_RATE_MONTHLY_BPS": 100,   # 1%/month delinquency interest
    "REFUND_INTEREST_MONTHLY_BPS": 50,  # 0.5%/month refund interest
    "LIEN_THRESHOLD_CENTS": 500000,     # $5,000
    "EXEMPTION_MIN_STAY_NIGHTS": 30,
}

# Penalty tier constants (PRD 3.7).
PENALTY = {
    "FLOOR_RATE": 0.10,
    "STEP": 0.05,
    "CAP_RATE": 0.25,
}

# Interest / refund month convention (PRD 3.7 / 3.9).
DAYS_PER_MONTH = 30

# Basis-point divisor (PRD 2.5).
BPS_DIVISOR = 10000

# Common test period boundaries (ISO 8601 UTC).
PERIOD_APR = ("2026-04-01T00:00:00Z", "2026-04-30T00:00:00Z")
PERIOD_JAN = ("2026-01-01T00:00:00Z", "2026-01-31T00:00:00Z")
PERIOD_FEB = ("2026-02-01T00:00:00Z", "2026-02-28T00:00:00Z")

# Logical-clock startup default (PRD 2.10).
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"
