"""Domain thresholds — numeric constants from the PRD's calculation rules (§2.4, §3)."""

# Logical clock (PRD §2.4): value the clock reads before it is ever set.
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"
# PRD §3.3: submission deadline for a fiscal-year-2027 program.
FY2027_SUBMISSION_DEADLINE = "2026-05-15T23:59:59Z"

# Funding split waterfall (PRD §3.4).
FEDERAL_SHARE_PCT = {
    "LARGE_HUB": 0.75,
    "MEDIUM_HUB": 0.80,
    "SMALL_HUB": 0.90,
    "NONHUB": 0.95,
}
STATE_PCT_OF_NONFEDERAL = 0.50

# CIP priority scoring (PRD §3.2).
SPONSOR_WEIGHTS = {
    "safety": 0.30, "preservation": 0.20, "capacity": 0.20,
    "security": 0.15, "environmental": 0.15,
}
FEDERAL_WEIGHTS = {
    "safety": 0.40, "capacity": 0.25, "preservation": 0.15,
    "security": 0.10, "environmental": 0.10,
}
NONCOMPLIANT_SAFETY_MULTIPLIER = 2
MULTI_AIRPORT_BONUS = 5
NONCOMPLIANT_FEDERAL_PENALTY = 10
SCORE_CAP = 100

# Grant amendment contingency (PRD §3.4).
CONTINGENCY_PCT = 0.10

# Sponsor assurance checklist (PRD §3.3).
ASSURANCE_TOTAL = 6
ASSURANCE_CODES = [
    "TITLE_VI", "BUY_AMERICAN", "DBE_PROGRAM",
    "ENVIRONMENTAL_REVIEW", "PREVAILING_WAGE", "AIRPORT_FEES",
]

# Operations-continuity limits on construction phases (PRD §3.8).
FULL_CLOSURE_MAX_HOURS = 72
NIGHT_ONLY_MAX_HOURS = 8
CONTRACTOR_BUFFER_HOURS = 24

# Contract field bounds (PRD §3.5).
RETAINAGE_PCT_MAX = 0.20
DBE_GOAL_PCT_MAX = 100
USEFUL_LIFE_YEARS_MIN = 1
USEFUL_LIFE_YEARS_MAX = 50

TEST_DEFAULTS = {
    "NPE_ENTITLEMENT_TOTAL": 5_000_000,
    "PROJECT_COST": 1_000_000,
    "SELECTION_BUDGET": 2_000_000,
    "AWARDED_VALUE": 500_000,
    "DBE_GOAL_PCT": 12.50,
    "RETAINAGE_PCT": 0.10,
    "GROSS_AMOUNT": 100_000,
}
