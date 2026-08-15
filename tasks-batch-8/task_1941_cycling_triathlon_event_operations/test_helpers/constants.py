"""Domain thresholds and constants from the PRD.

PRD references:
- Logical clock startup default (PRD "The Logical Clock and Race Time").
- Swim-cancel temperature bounds (PRD "Swim Safety, Transition Security...").
- Refund tiers and processing fee (PRD "Registration, Wave Assignment, and
  Withdrawal Refunds").
- Penalty seconds per kind/tier (PRD "Penalties, Appeals, Finalization...").
- Permit corridor buffer (PRD "Course Permitting and Road-Closure Coordination").
- Appeal window default (PRD "Course Permitting..." event creation).
"""

# Logical clock startup default: before any operator intervention the clock
# reads exactly this instant and never falls back to wall-clock time.
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# Standard event start used across the suite.
EVENT_START_ISO = "2026-10-15T08:00:00Z"
EVENT_START_YEAR = 2026

# Swim safety decision bounds (inclusive on the proceed side).
MIN_SWIM_TEMP_C = 12.0
MAX_SWIM_TEMP_C = 31.0

# Refund tier ladder (days until event -> refundable base fraction).
TIER1_DAYS = 60
TIER1_PCT = 0.75
TIER2_DAYS = 30
TIER2_PCT = 0.50
PROCESSING_FEE_PCT = 0.10

# Penalty severity table (integer seconds).
DRAFTING_FIRST_OFFENSE_SECONDS = 120
DRAFTING_SECOND_OFFENSE_SECONDS = 300
DRAFTING_DSQ_PRIOR_COUNT = 2
COURSE_VIOLATION_SECONDS = 300
EQUIPMENT_SECONDS = 60

# Permit corridor buffer in minutes (strict inequality; exactly 30 min allowed).
PERMIT_BUFFER_MINUTES = 30

# Appeal window default (minutes) applied when event creation omits it.
DEFAULT_APPEAL_WINDOW_MINUTES = 60

# Common fixture values.
DEFAULT_ENTRY_FEE_CENTS = 20000
DEFAULT_WATER_POOL_UNITS = 1000
