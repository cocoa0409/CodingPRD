"""Domain thresholds — numeric constants from PRD calculations (§2.4, §2.6, §3)."""

# Logical clock startup default (PRD §2.4).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Conventional operator id for the very first POST /employees bootstrap call
# (registering the EHS manager's own Employee record).
OPERATOR_ID = "00000000-0000-4000-8000-000000000001"

# Risk scoring (PRD §3.8).
RISK_WEIGHTS = {
    "NEAR_MISS": 1,
    "FIRST_AID": 2,
    "PROPERTY_DAMAGE": 3,
    "INJURY": 5,
}
TIER_MEDIUM_MIN = 5
TIER_HIGH_MIN = 10
RISK_WINDOW_DAYS = 365

# Training (PRD §3.4).
TRAINING_VALIDITY_DAYS = 365
ASSIGNMENT_DUE_DAYS = 30

# Minor-servicing duration caps by risk tier (PRD §3.9).
MINOR_SERVICING_CAP = {"LOW": 480, "MEDIUM": 120, "HIGH": 0}

# Annual audit period (PRD §3.3, §3.7).
AUDIT_PERIOD_DAYS = 365

# Pagination (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MAX_LIMIT = 100
