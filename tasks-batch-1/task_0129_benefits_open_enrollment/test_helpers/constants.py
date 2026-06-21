"""Domain thresholds and pay-period constants from the PRD's calculations (Sections 3.5, 3.10)."""

# Pay periods per year by payroll schedule (PRD Section 3.5).
SEMI_MONTHLY_PERIODS = 24
BIWEEKLY_PERIODS = 26

# ACA affordability percentage (PRD Section 3.10): 9.02% expressed as a decimal factor.
ACA_AFFORDABILITY_PCT = 0.0902

# Life-event approval window (PRD Section 3.6): event_date must fall within 30 days of the clock.
LIFE_EVENT_WINDOW_DAYS = 30

# Voluntary-life coverage unit size (PRD Section 3.5): one $1000 unit == 100000 cents.
VOLUNTARY_LIFE_UNIT_CENTS = 100000

# Pagination bounds (PRD Section 2.3).
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# A syntactically valid v4-form UUID that does not correspond to any created resource.
NON_EXISTENT_V4_UUID = "00000000-0000-4000-8000-000000000000"
