"""Domain thresholds — numeric constants from the PRD calculation rules."""

# OAA age eligibility (PRD §3.1)
OAA_MIN_AGE = 60

# Income tier / federal poverty line (PRD §3.1)
FPL_BASE_MONTHLY_CENTS = 125500
FPL_INCREMENT_CENTS = 44000
TIER_A_MAX_RATIO = 1.00
TIER_B_MAX_RATIO = 1.85

# Nutritional risk band (PRD §3.2)
NUTRITION_MODERATE_MIN = 3
NUTRITION_HIGH_MIN = 6

# Functional level band (PRD §3.2)
FUNCTIONAL_PARTIAL_MIN = 2
FUNCTIONAL_DEPENDENT_MIN = 5

# Weekly meal count (PRD §3.4)
FROZEN_DAYS_COVERED = 7
MAX_WEEKLY_MEALS = 21

# Suggested contribution pricing (PRD §3.4)
BASE_MEAL_COST_CENTS = 725
WEEKS_PER_MONTH = 4
TIER_FACTORS = {"TIER_A": 0.15, "TIER_B": 0.35, "TIER_C": 0.55}

# Welfare-alert severity (PRD §3.6)
WELFARE_HIGH_SEVERITY_MIN = 2

# Pagination (PRD §2.3)
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
