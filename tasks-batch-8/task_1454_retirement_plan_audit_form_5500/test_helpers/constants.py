"""Domain thresholds and numeric constants named in the PRD."""

# Participant count determination (PRD §3.2)
AUDIT_THRESHOLD = 100
EIGHTY_120_LOW = 80
EIGHTY_120_HIGH = 120
SMALL_PLAN_SAFE_HARBOR_DAYS = 7
LARGE_PLAN_ADMIN_FEASIBLE_DAYS = 3

# Lost earnings on late deposit (PRD §3.7)
VFCP_UNDERPAYMENT_ANNUAL_PCT = 8.0
EPCRS_PLAN_ANNUAL_PCT = 5.0
DAY_BASIS = 365

# Coverage test (PRD §3.5)
COVERAGE_RATIO_PASS_PCT = 70.00

# Schedule C fee disclosure (PRD §3.8)
SCHEDULE_C_THRESHOLD_CENTS = 500000

# DFVCP penalty (PRD §3.9)
DFVCP_PER_DAY_CENTS = 1000
DFVCP_CAP_SMALL_CENTS = 75000
DFVCP_CAP_LARGE_CENTS = 200000

# Excise tax on late corrective distributions (PRD §3.7)
EXCISE_TAX_PCT = 10

# Logical clock startup default (PRD §2.10)
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Common census template values
DEFAULT_COMPENSATION_CENTS = 10_000_000
DEFAULT_EIN = "12-3456789"
PLAN_YEAR_START_2025 = "2025-01-01"
PLAN_YEAR_END_2025 = "2026-01-01"
