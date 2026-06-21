"""Domain thresholds — numeric constants from PRD calculations."""

# Ancillary meal/activity charge constants (PRD 3.7)
MEAL_CHARGE_CENTS = 850
ACTIVITY_BONUS_CENTS = 200

# Default field values declared by the PRD
DEFAULT_LOCK_IN_DAYS = 30
DEFAULT_LOC_VALIDITY_DAYS = 365
DEFAULT_NF_THRESHOLD = 60
DEFAULT_MEDICARE_ONLY_SUPPLEMENT_CENTS = 0
DEFAULT_PRORATION_MODE = "FULL_MONTH"
DEFAULT_REQUIRED_DISCIPLINES = ["RN", "SW", "MEDICAL_DIRECTOR"]

# Common test rates used by many design instances
TEST_DEFAULTS = {
    "medicaid_monthly_rate_cents": 350000,
    "medicare_monthly_rate_cents": 280000,
    "medicare_only_supplement_cents": 50000,
}
