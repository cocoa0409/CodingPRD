"""Domain thresholds — canonical fixture values and expected computed figures.

Canonical fixture (dates and money figures traceable to PRD §3.4):
  clock 2025-01-10 at move-in completion; 2026-08-01 at move-out completion
  => 568-day span. Deposit 200,000c at 300bp ACTUAL_DAYS => interest 9,337c.
  Paint damage: replacement 90,000c, applied 2025-08-01, life 3y (1,095d),
  age 365d, residual 730/1095 => charge 60,000c.
  Standard refund: 200,000 + 9,337 - 60,000 = 149,337c.
"""

DAYS_PER_YEAR = 365

# Canonical clock values
CLOCK_MOVE_IN = "2025-01-10T00:00:00Z"
CLOCK_MOVE_OUT = "2026-08-01T00:00:00Z"
CLOCK_ISSUE_TIMELY = "2026-08-10T00:00:00Z"
CLOCK_ISSUE_ON_DEADLINE = "2026-08-22T12:00:00Z"
CLOCK_ISSUE_LATE = "2026-08-23T00:00:00Z"
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Canonical expected figures (integer cents)
CANONICAL_INTEREST_ACTUAL_DAYS = 9_337
CANONICAL_INTEREST_WHOLE_YEARS = 6_000
CANONICAL_PAINT_DAMAGE = 60_000
CANONICAL_DEPOSIT = 200_000
CANONICAL_REFUND_DUE = 149_337  # 200000 + 9337 - 60000
CANONICAL_REFUND_DUE_WITH_CLEANING = 141_337  # 200000 + 9337 - 68000

# Key/fob/lock charges under the canonical fee schedule
KEY_CHARGE_CENTS = 5_000
FOB_CHARGE_CENTS = 7_500
LOCK_CHANGE_CENTS = 12_000

# Deadline arithmetic: move_out 2026-08-01 + 21 days = 2026-08-22
CANONICAL_DEADLINE_ON = "2026-08-22"
# Stale check: sent 2026-08-10 + 180 days = 2027-02-06
STALE_THRESHOLD_DATE = "2027-02-06T00:00:00Z"
STALE_ONE_DAY_PAST = "2027-02-07T00:00:00Z"
STALE_FAR_PAST = "2027-02-20T00:00:00Z"
# Dispute window: issued 2026-08-10 + 30 days = 2026-09-09 (inclusive last day)
DISPUTE_WINDOW_LAST_DAY = "2026-09-09T23:00:00Z"
DISPUTE_WINDOW_CLOSED_DAY = "2026-09-10T00:00:00Z"
