"""Domain thresholds — numeric constants from the PRD's calculations and rules."""

# First-offender eligibility ceiling (PRD §3.2): qualifies only while count < 1.
FIRST_OFFENDER_MAX_PRIOR = 1

# Arraignment window (PRD §3.2): offense_date 00:00Z + 30 days.
ARRAIGNMENT_WINDOW_DAYS = 30

# Logical clock startup default (PRD §2.5).
DEFAULT_CLOCK_UTC = "2026-03-01T00:00:00Z"

# Fine assessment (PRD §3.4 / §3.5).
COURT_FEE = 50.00
SURCHARGE_TIER_1_MAX = 100.00
SURCHARGE_TIER_1_RATE = 0.20
SURCHARGE_TIER_2_MAX = 500.00
SURCHARGE_TIER_2_RATE = 0.30
SURCHARGE_TIER_3_RATE = 0.35
SURCHARGE_CAP = 150.00
SEVERITY_MULTIPLIER_INFRACTION = 1.0
SEVERITY_MULTIPLIER_MISDEMEANOR = 1.5

# Installment plans (PRD §3.7).
INSTALLMENT_COUNT_MIN = 2
INSTALLMENT_COUNT_MAX = 12
INSTALLMENT_MIN_BALANCE = 100.00
INSTALLMENT_INTERVAL_DAYS = 30

# Compliance percentage weights (PRD §3.6).
WEIGHT_SERVICE = 0.5
WEIGHT_CLASS = 0.3
WEIGHT_FINANCIAL = 0.2

# Reinstatement (PRD §3.8).
LATE_PENALTY = 75.00
