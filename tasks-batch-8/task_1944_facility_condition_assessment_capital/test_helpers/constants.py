"""Domain thresholds — numeric constants from PRD calculations (§2.5, §3)."""

# Escalation compounding base year (PRD §3.7).
BASE_YEAR = 2026

# Deficiency priority-score weights and bonuses (PRD §3.4).
SEVERITY_WEIGHT = 0.6
URGENCY_WEIGHT = 0.4
CODE_BONUS = 10
ACCESSIBILITY_BONUS = 5

# Refresh-health FCI bands (PRD §3.9); comparisons are inclusive (>=).
WATCH_FCI_THRESHOLD = 0.05
CRITICAL_FCI_THRESHOLD = 0.10

# Remaining-useful-life rules (PRD §3.2).
FAILED_RATING = 1            # rating 1 forces RUL 0
POOR_RATING = 2              # rating 2 caps RUL at POOR_RUL_CAP
POOR_RUL_CAP = 2
PESSIMISTIC_RUL_PENALTY = 2  # stress-test variant subtracts a further 2 years

# Server logical clock startup default (PRD §2.8).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_YEAR = 2026

SYSTEM_CATEGORIES = [
    "HVAC", "ROOF", "ENVELOPE", "ELECTRICAL", "PLUMBING",
    "FIRE_PROTECTION", "CONVEYANCE", "INTERIOR", "SITE", "STRUCTURE",
]

TEST_DEFAULTS = {
    "GROSS_SQUARE_FEET": 10000,
    "REPLACEMENT_COST_CENTS": 100_000_000,
    "ANNUAL_BUDGET_CENTS": 500_000_000,
    "ESCALATION_RATE": 0.0,
    "START_YEAR": 2027,
    "HORIZON_YEARS": 1,
}
