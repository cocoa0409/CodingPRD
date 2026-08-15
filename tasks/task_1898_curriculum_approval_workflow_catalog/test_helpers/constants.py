"""Domain thresholds — numeric constants named in the PRD.

Substantive-change scoring (PRD §3.6), teach-out arithmetic (PRD §3.8),
the credit-hour workload check (PRD §3.4), and the logical clock default
(PRD §2.5).
"""

# Logical clock (PRD §2.5): startup default; never falls back to wall clock.
DEFAULT_LOGICAL_CLOCK = "2026-08-01T00:00:00Z"

# Substantive-change score constants (PRD §3.6).
SCORE_BASE_NEW_COURSE = 20
SCORE_BASE_COURSE_CHANGE = 10
SCORE_BASE_DEACTIVATION = 30
CREDIT_DELTA_FACTOR = 25
CREDIT_DELTA_RATIO = 0.25
PREREQ_PER_LINK = 10
PREREQ_FACTOR_CAP = 20
CROSS_LISTING_FACTOR = 15
TEACH_OUT_FACTOR = 20
NOTIFY_THRESHOLD = 50

# Teach-out arithmetic (PRD §3.8).
COHORTS_DRAINED_PER_TERM = 2
CATALOG_TEACH_OUT_TERMS = 4
SECTION_CAPACITY = 15
SECTION_COST_CENTS = 400000

# Credit-hour workload check (PRD §3.4).
WEEKS_PER_TERM = 15
CARNEGIE_HOURS_PER_CREDIT = 45
CREDIT_TOLERANCE = 0.5

# Standard actor identifiers used across setups.
REGISTRAR_USER_ID = "reg-1"
DEFAULT_PROPOSER_ID = "fac-001"
SECOND_PROPOSER_ID = "fac-002"
COMMITTEE_USER_ID = "cc-1"
SENATE_USER_ID = "sen-1"
