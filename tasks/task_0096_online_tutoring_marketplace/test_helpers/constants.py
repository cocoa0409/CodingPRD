"""Domain thresholds and standard test values from the PRD calculations.

These are the numeric constants the PRD names for the marketplace's pricing,
scheduling, and reliability rules, plus the canonical commission-policy values
used across the test suite's setup chains.
"""

# --- Scheduling / billing thresholds (PRD Sections 3.5-3.7) ---
OVERTIME_GRACE_MINUTES = 15          # billed minutes may exceed planned by at most 15
FLOOR_MINUTES = 1                    # a delivered session bills at least 1 minute
STUDENT_GAP_MINUTES = 15             # student-calendar buffer
MIN_PLANNED_MINUTES = 15
MAX_PLANNED_MINUTES = 240
MIN_ACTUAL_MINUTES = 1
MAX_ACTUAL_MINUTES = 480

# --- Tutor rate bounds (PRD Section 3.2) ---
MIN_BASE_HOURLY_RATE_CENTS = 1000
MAX_BASE_HOURLY_RATE_CENTS = 50000

# --- Student grade bounds (PRD Section 3.4) ---
MIN_GRADE_LEVEL = 1
MAX_GRADE_LEVEL = 13

# --- Reliability scoring (PRD Section 3.10) ---
NO_SHOW_PENALTY = 8
ARBITRATED_REFUND_PENALTY = 12
SCORE_FLOOR = 0
SCORE_CEILING = 100

# --- Negotiation caps (PRD Section 3.9) ---
MAX_NEGOTIATION_ROUNDS = 3
MAX_RESCHEDULE_COUNT = 3

# --- Pagination defaults (PRD Section 2.3) ---
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Canonical commission policy used throughout the design chains ---
# tier_breakpoints_cents [0, 100000, 1000000] / tier_rates_bps [2500, 1500, 800]
POLICY_TIER_BREAKPOINTS_CENTS = [0, 100000, 1000000]
POLICY_TIER_RATES_BPS = [2500, 1500, 800]
POLICY_TRIAL_COMMISSION_BPS = 5000
POLICY_TRIAL_MAX_BILLED_MINUTES = 30
POLICY_REFUND_WINDOW_HOURS = 168
