"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Deposit assessment (PRD §3.2)
TIER1_MW = 20                  # first twenty MW billed at the tier-1 rate
TIER1_RATE_CENTS = 100000      # cents per MW within tier 1
TIER2_RATE_CENTS = 250000      # cents per MW beyond tier 1
CAPACITY_MULTIPLIER = 1.2      # service_type CAPACITY multiplier
ENERGY_ONLY_MULTIPLIER = 1.0   # service_type ENERGY_ONLY multiplier
EXPEDITED_MAX_MW = 5           # STORAGE at or below this is EXPEDITED
EXPEDITED_FLAT_CENTS = 300000  # flat EXPEDITED deposit
MAX_PROJECT_CAPACITY_MW = 500  # nameplate ceiling on a project

# Deposit forfeiture schedule (PRD §3.7)
FORFEIT_PCT_EARLY = 0.10       # SUBMITTED / QUEUED / READY
FORFEIT_PCT_STUDY = 0.50       # IN_STUDY / STUDY_COMPLETE / RESTUDY_REQUIRED
FORFEIT_PCT_AGREEMENT = 1.00   # AGREEMENT_PENDING / AGREEMENT_EXECUTED

# Cost allocation (PRD §3.4)
HEAD_COUNT_FRACTION = 0.5      # FINAL basis: half by headcount, half by capacity

# Agreement deadlines and extensions (PRD §3.6)
EXECUTION_DEADLINE_DAYS = 90
MAX_EXTENSION_COUNT = 2
EXTENSION_NOTICE_DAYS = 30
EXTENSION_MAX_SHIFT_DAYS = 365

# Logical clock (PRD §2.6)
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_TARGET_COD = "2027-06-01T00:00:00Z"
# issued_at default + 90 days
DEFAULT_EXECUTION_DEADLINE = "2026-10-30T00:00:00Z"

TEST_DEFAULTS = {
    "TOTAL_COST_CENTS": 1000000,
    "CLUSTER_CAPACITY_MW": 200,
    "REGION": "WEST",
}
