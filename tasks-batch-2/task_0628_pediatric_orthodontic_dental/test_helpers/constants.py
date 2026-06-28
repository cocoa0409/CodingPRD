"""Domain thresholds - numeric constants from PRD calculations.

Generic NON_EXISTENT_UUID comes from the framework.
"""

# Modality multipliers (PRD 3.5): INVISALIGN multiplies summed phase fees by
# 1.15, BRACES by 1.00.
INVISALIGN_MULTIPLIER = 1.15
BRACES_MULTIPLIER = 1.00

# Family discount ceiling (PRD 2.5 / 3.5): the discount subtracted from a
# plan's gross fee can never exceed 75000 cents.
DISCOUNT_CAP_CENTS = 75000

# Family discount tiers (PRD 3.5): <2 in-treatment plans -> 0; ==2 -> 0.05;
# >=3 -> 0.10.
TIER2_PCT = 0.05
TIER3_PCT = 0.10

# Installment schedule (PRD 3.7): one month is 30 days.
MONTH_STEP_DAYS = 30

# Default startup clock value (PRD 2.4).
DEFAULT_CLOCK = "2026-01-01T00:00:00.000Z"

# A well-formed UUID that resolves to no resource (for 404 tests).
MISSING_UUID = "00000000-0000-4000-8000-000000000000"
