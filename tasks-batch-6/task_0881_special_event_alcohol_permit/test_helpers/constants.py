"""Domain thresholds — numeric constants from the PRD's calculations and rules."""
from prd_bench_local_runner.testing import NON_EXISTENT_UUID  # noqa: F401

# Permit fee (PRD §3.3 / §3.9)
BASE_PERMIT_FEE_CENTS = 5000
PER_ATTENDEE_SURCHARGE_CENTS = 37.5
SALES_SURCHARGE_RATE = 0.0125

# Deposit (PRD §3.3)
DEPOSIT_CENTS = 20000

# Security staffing (PRD §3.4)
ATTENDEES_PER_GUARD = 75
MIN_GUARDS = 2
LONG_EVENT_HOURS = 5
HIGH_OCCUPANCY_FRACTION = 0.90

# Violation fines (PRD §3.8)
FINE_MINOR_CENTS = 2500
FINE_MAJOR_CENTS = 10000
FINE_CRITICAL_CENTS = 25000
REPEAT_MULTIPLIER = 1.5

# Insurance coverage tiers (PRD §3.4)
COVERAGE_TIER_1_CENTS = 100000000
COVERAGE_TIER_2_CENTS = 200000000
COVERAGE_TIER_3_CENTS = 500000000

# Closeout (PRD §3.9)
CLEANUP_FEE_CENTS = 15000

# Temporal rules (PRD §3.3 / §3.6)
MIN_SUBMISSION_LEAD_DAYS = 14
INSPECTION_BUFFER_MINUTES = 60

# Review workflow (PRD §3.5)
REQUIRED_AGENCIES = ["POLICE", "FIRE", "ALCOHOL_BOARD"]
TOTAL_REVIEW_COUNT = 3

# Canonical reference figures used across the standard Riverside fixture:
#   attendance 151, requested_sales_limit 250050  ->  fee 13789, deposit 20000
#   balance_due after submit = 33789
STANDARD_FEE_CENTS = 13789
STANDARD_BALANCE_DUE_CENTS = 33789

# Logical-clock startup default (PRD §4).
CLOCK_DEFAULT = "2026-05-01T00:00:00Z"
