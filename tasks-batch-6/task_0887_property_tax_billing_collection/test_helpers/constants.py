"""Domain thresholds — numeric constants from the PRD calculations (Section 3)."""

# Delinquency rates (PRD 3.5).
PENALTY_RATE = 0.05           # 5% one-time penalty
INTEREST_RATE_MONTHLY = 0.01  # 1%/month whole-month interest

# Referral / redemption (PRD 3.8).
LIEN_REFERRAL_THRESHOLD_CENTS = 50000   # $500.00 statutory lien-referral floor
REDEMPTION_PERIOD_DAYS = 365
DAYS_PER_YEAR = 365           # per-diem payoff projection divisor (PRD 3.5)

# Installment split (PRD 3.2).
INSTALLMENT_COUNT = 2

# Standard test tax-year shape.
STANDARD_YEAR = 2025
STANDARD_MILLAGE = 20.0
FIRST_DUE = "2026-06-15T00:00:00Z"
SECOND_DUE = "2026-09-15T00:00:00Z"

# Logical-clock startup default (PRD 2.8).
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"

# A well-formed but non-existent UUID for not-found probes.
MISSING_UUID = "00000000-0000-0000-0000-000000000000"
