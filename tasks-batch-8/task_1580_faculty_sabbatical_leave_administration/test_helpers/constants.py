"""Domain thresholds — numeric constants from the PRD's calculation rules."""

THRESHOLDS = {
    # PRD 3.2/3.3: sabbatical eligibility and credit cost
    "MIN_CERTIFIED_SERVICE_MONTHS": 72,
    "SABBATICAL_CREDIT_COST_PER_SEMESTER": 36,
    "CREDIT_RESTORE_PER_UNUSED_MONTH": 6,
    # PRD 3.8: salary/offset computation
    "SEMESTER_MONTHS": 6,
    "MAX_FELLOWSHIP_OFFSET_PCT": 0.50,
    # PRD 3.4: committee composite
    "WEIGHT_MERIT": 0.45,
    "WEIGHT_CURRICULUM": 0.35,
    "WEIGHT_FEASIBILITY": 0.20,
    "REVIEW_QUORUM": 3,
    "DROP_LOWEST_MIN_REVIEWS": 4,
    # PRD 3.5: coverage pricing
    "REPLACEMENT_COST_PER_COURSE": 8000.00,
    # PRD 3.1: posture thresholds (inclusive boundaries)
    "POSTURE_CONSTRAINED_THRESHOLD": 0.70,
    "POSTURE_FROZEN_THRESHOLD": 0.95,
    # PRD 3.8: department simultaneous active-leave cap
    "DEPT_MAX_ACTIVE_LEAVES": 2,
}

TEST_DEFAULTS = {
    "DEPARTMENT_POOL": 160000.00,
    "REVIEW_DEPARTMENT_POOL": 50000.00,
    "BASE_SALARY": 120000.00,
    "HIRE_DATE": "2020-08-01T00:00:00Z",
    "CYCLE_YEAR": "2027-2028",
    "SABBATICAL_START": "2027-01-01T00:00:00Z",
    "SABBATICAL_END": "2027-07-01T00:00:00Z",
    "SABBATICAL_END_2SEM": "2028-01-01T00:00:00Z",
}

# PRD 2.5: server startup clock
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
