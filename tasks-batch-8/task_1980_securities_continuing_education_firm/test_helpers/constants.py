"""Domain thresholds — numeric constants from the PRD (§3.4-§3.8, §2.4)."""

# Logical clock startup default (PRD §2.4).
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Firm element requirement (PRD §3.6)
    "MIN_REQUIRED_HOURS": 6,
    "BASE_HOURS_RR": 12,
    "BASE_HOURS_PRINCIPAL": 16,
    "PER_PRODUCT_SURCHARGE": 2,
    "SURCHARGE_CAP": 3,
    # Assignment clock (PRD §3.5)
    "ASSIGNMENT_WINDOW_DAYS": 120,
    "GRACE_DAYS": 30,
    # Enrollment validity (PRD §3.4)
    "ENROLLMENT_VALIDITY_DAYS": 90,
    "MAX_ATTEMPTS": 3,
    # State CE carryover (PRD §3.8)
    "CARRYOVER_CAP_HOURS": 6,
    # Reported-hours rounding unit (PRD §2.8)
    "ROUNDING_UNIT": 0.5,
}

TEST_DEFAULTS = {
    "CREDIT_HOURS": 1.0,
    "MIN_PASSING_SCORE": 70,
    "PLAN_YEAR": 2026,
    "CYCLE_YEAR": 2026,
    "SESSION_CAPACITY": 10,
    "LICENSE_REQUIRED_HOURS": 24,
    "VOID_JUSTIFICATION": "audit correction justification text",
}
