"""Domain thresholds — numeric constants from the PRD calculations.

Generic NON_EXISTENT_UUID is re-exported from the framework via the barrel.
"""

# Financial-aid banding (PRD §3.6). Cents.
HOUSEHOLD_ALLOWANCE_CENTS = 600_000      # $6,000 per additional member
TIER_1_CEILING_CENTS = 6_000_000         # $60,000
TIER_2_CEILING_CENTS = 4_000_000         # $40,000
TIER_3_CEILING_CENTS = 2_500_000         # $25,000

# Tier discount fractions (PRD §3.6).
TIER_DISCOUNT = {"NONE": 0.00, "TIER_1": 0.20, "TIER_2": 0.40, "TIER_3": 0.60}

# Subscription defaults (PRD §3.6).
DEFAULT_BASE_WEEKLY_FEE_CENTS = 9900
DEFAULT_WEEKLY_CREDIT_GRANT = 1
MAX_WEEKLY_CREDIT_GRANT = 4

# Billing period (PRD §3.6 / §3.7).
TOTAL_DAYS_PER_PERIOD = 7

# Pause horizon (PRD §3.7): resume_on no later than 84 days after current_period_start.
PAUSE_MAX_DAYS = 84

# Credit expiry (PRD §3.6): granted period_end + 28 days.
CREDIT_EXPIRY_DAYS = 28

# Cancellation window (PRD §3.5): within-window if < 24h before starts_at.
CANCEL_WINDOW_HOURS = 24

# Therapist scheduling buffer (PRD §3.5): sessions must be >= 15 min apart.
THERAPIST_BUFFER_MINUTES = 15

# Match-score weights (PRD §3.3). Integer arithmetic, no rounding.
SPECIALTY_WEIGHT = 10
STATE_WEIGHT = 25
SEVERITY_WEIGHT = 2

# Intake safety gate (PRD §3.1): severity >= 8 forces clinician review.
INTAKE_SEVERITY_GATE = 8

# Therapist default caseload cap (PRD §3.2).
DEFAULT_MAX_ACTIVE_CASELOAD = 30

# Logical-clock startup default (PRD §2.10).
CLOCK_DEFAULT_ISO = "2026-05-01T00:00:00Z"
