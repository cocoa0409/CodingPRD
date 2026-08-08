"""Domain thresholds — numeric constants from the PRD calculations.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Ability-to-pay installment (PRD §3.2)
ABILITY_TO_PAY_RATE = 0.10
MIN_INSTALLMENT_CENTS = 2500

# Delinquency & plan due interval (PRD §3.2, §3.9)
DELINQUENCY_GRACE_DAYS = 30
PLAN_DUE_INTERVAL_DAYS = 30

# Aging & write-off (PRD §3.7)
WRITEOFF_AGE_DAYS = 1825

# Wage-assignment capacity (PRD §3.8)
MAX_MONTHLY_WITHHOLD_CENTS = 50000

# Default priority ranks by obligation type (PRD §3.1)
DEFAULT_PRIORITY_RANK = {
    "RESTITUTION": 1,
    "COURT_FEE": 2,
    "FINE": 3,
    "SURCHARGE": 4,
}

# Server logical-clock startup default (PRD §2.6)
CLOCK_DEFAULT_UTC = "2026-05-01T00:00:00Z"
