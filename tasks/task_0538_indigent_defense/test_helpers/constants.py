"""Domain thresholds — numeric constants from PRD calculations."""

# Eligibility determination (PRD 3.2)
FPL_BASE_CENTS = 1_500_000
FPL_INCREMENT_CENTS = 500_000
ELIGIBLE_MULT = 1.25
PARTIAL_MULT = 2.00
ASSET_INELIGIBLE_CAP_CENTS = 2_000_000

# Partial-eligibility contribution (PRD 3.2)
ASSET_CONTRIB_FLOOR_CENTS = 500_000
INCOME_RATE = 0.10
ASSET_RATE = 0.05

# Case weight (PRD 3.3, 3.4)
BASE_WEIGHT = {
    "FELONY_A": 4.0,
    "FELONY_B": 2.5,
    "MISDEMEANOR": 1.0,
    "JUVENILE": 1.5,
    "APPEAL": 3.0,
}
COMPLEXITY_MULT = {
    "STANDARD": 1.0,
    "COMPLEX": 1.5,
    "CAPITAL": 2.0,
}
CO_DEF_INCREMENT = 0.25

# Panel-fee case fee cap (PRD 3.7)
CASE_FEE_CAP = {
    "FELONY_A": 750_000,
    "FELONY_B": 500_000,
    "MISDEMEANOR": 200_000,
    "JUVENILE": 300_000,
    "APPEAL": 600_000,
}

# Service authorization cap (PRD 3.6)
SERVICE_CAP = {
    "INVESTIGATOR": 250_000,
    "EXPERT_PSYCH": 500_000,
    "EXPERT_FORENSIC": 750_000,
}

# Recoupment schedule (PRD 3.8)
RECOUP_SCHEDULE = {
    "FELONY_A": 50_000,
    "FELONY_B": 40_000,
    "MISDEMEANOR": 15_000,
    "JUVENILE": 10_000,
    "APPEAL": 35_000,
}

# Office budget posture (PRD 2.10)
BUDGET_RESTRICT_RATIO = 0.90

# Attorney calendar travel buffer, minutes (PRD 3.5)
TRAVEL_BUFFER_MINUTES = 30

# Logical clock (PRD 2.11)
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"

# Convenient large budget for tests that never intend to restrict the office.
LARGE_BUDGET_CENTS = 100_000_000
