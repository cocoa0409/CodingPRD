"""Domain thresholds and shared values from the PRD's calculation rules."""

# Logical clock reading before any client call has been made (PRD: the clock
# "reads exactly 2026-08-01T00:00:00Z" before any call).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Ramp computation constants (PRD ramp rules).
RAMP_DAY_CUTOFF = 15          # hire day after the 15th makes the hire month tenure month 0
MONTHS_PER_PLAN = 12          # every plan year runs twelve calendar months

# Credit transition constant (PRD mid-year change rules).
SNAPSHOT_DAY_CUTOFF = 15      # MONTH_SNAPSHOT transfers the transition month when day <= 15

# Reconciliation tolerance (PRD reconciliation rules).
TOLERANCE_PCT = 10            # |bottom_up - top_down| * 100 <= top_down * 10 blends

# Dispute review SLA (PRD dispute rules).
REVIEW_SLA_DAYS = 7           # escalate when current date is strictly more than 7 days past filed_date

# Standard ramp schedule used across tests: 0.00, 0.25, 0.50, 0.75, then 1.00.
STANDARD_RAMP_MULTIPLIERS = [0.00, 0.25, 0.50, 0.75,
                             1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00]

# All-zero ramp schedule: legal (non-decreasing, within [0.00, 1.00]).
ZERO_RAMP_MULTIPLIERS = [0.00] * 12

# Default plan-year shape used by factories: calendar year 2027.
DEFAULT_PLAN_START = "2027-01-01"
DEFAULT_PLAN_END = "2027-12-31"
DEFAULT_LOCK_DATE = "2027-01-15"

TEST_DEFAULTS = {
    "COMPANY_TARGET_CENTS": 100000,
    "PRODUCTIVITY_PER_REP_CENTS": 1000000,
    "TERRITORY_POTENTIAL_CENTS": 100,
    "TERRITORY_HEADCOUNT_CAPACITY": 2,
    "ACCOUNT_ANNUAL_POTENTIAL_CENTS": 50000,
    "VETERAN_HIRE_DATE": "2025-01-05",
}
