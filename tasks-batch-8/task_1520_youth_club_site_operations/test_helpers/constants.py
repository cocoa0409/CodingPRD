"""Domain thresholds and shared defaults from PRD Sections 2-3."""

# --- Eligibility tier limits (PRD 3.2) ---
# free_limit(size)    = FREE_BASE_CENTS + (size - 1) * FREE_STEP_CENTS
# reduced_limit(size) = REDUCED_BASE_CENTS + (size - 1) * REDUCED_STEP_CENTS
FREE_BASE_CENTS = 1_500_000
FREE_STEP_CENTS = 500_000
REDUCED_BASE_CENTS = 2_000_000
REDUCED_STEP_CENTS = 650_000

# Tier multipliers applied to base_weekly_fee_cents (PRD 3.2)
TIER_MULTIPLIER = {"FREE": 0.0, "REDUCED": 0.5, "PAID": 1.0}

# Behavior points (PRD 3.8)
INCIDENT_POINTS = {"LEVEL_1": 1, "LEVEL_2": 3, "LEVEL_3": 8}
BEHAVIOR_WINDOW_DAYS = 90
DISCIPLINE_WATCH_THRESHOLD = 10

# Seasonal meal multiplier for June/July/August days (PRD 3.9)
SUMMER_MULTIPLIER = 1.10

# Default per-site meal reimbursement rates, integer cents per tier per meal type
DEFAULT_MEAL_RATES = {
    "BREAKFAST": {"FREE": 225, "REDUCED": 195, "PAID": 45},
    "SNACK": {"FREE": 110, "REDUCED": 55, "PAID": 15},
    "SUPPER": {"FREE": 315, "REDUCED": 275, "PAID": 55},
}

# Default site configuration used across scenarios
DEFAULT_SITE = {
    "youth_capacity": 60,
    "standard_ratio": 15,
    "elevated_ratio": 8,
    "base_weekly_fee_cents": 5000,
    "registration_fee_cents": 2500,
    "max_arrears_cents": 10000,
}

# Credential expiry that is comfortably in the future for August 2026 scenarios
FAR_FUTURE_EXPIRY = "2027-01-01T00:00:00Z"

# Startup logical clock value used by most setups (PRD 2.4 default is
# 2026-08-01T00:00:00Z; setups move it to a working morning)
DEFAULT_CLOCK = "2026-08-01T09:00:00Z"
