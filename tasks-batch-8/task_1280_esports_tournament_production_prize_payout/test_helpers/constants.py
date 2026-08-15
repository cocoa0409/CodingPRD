"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Prize pool waterfall (PRD §3.7)
MIN_PLACEMENT_CENTS = 100000          # minimum placement payout floor
PCT_FIRST = 50
PCT_SECOND = 25
PCT_THIRD = 12.5

# Withholding (PRD §3.8)
DOC_THRESHOLD_CENTS = 60000           # inclusive doc gate
BACKUP_WITHHOLDING_PCT = 24
FOREIGN_WITHHOLDING_PCT = 30

# Talent fee (PRD §3.10)
HOURS_PER_DAY_UNIT = 8
OVERTIME_MULT = 1.5
CROSS_REGION_UPLIFT_PCT = 15
ROYALTY_BAND1_MAX_CENTS = 200000      # base < this -> 0%
ROYALTY_BAND2_MAX_CENTS = 500000      # base < this -> 5%
ROYALTY_BAND2_PCT = 5
ROYALTY_BAND3_PCT = 10

# Strikes (PRD §3.9)
STRIKE_LIMIT = 3
STRIKE_WINDOW_DAYS = 365

# Matches (PRD §3.4, §3.5)
BUFFER_MINUTES = 15                   # server teardown buffer per booking
TACTICAL_PAUSE_LIMIT = 2
MINOR_AGE_YEARS = 18
DISPUTE_WINDOW_HOURS = 24

# Logical clock (PRD §2.5)
CLOCK_START = "2026-08-01T00:00:00Z"
LOCK_INSTANT = "2026-08-10T00:00:00Z"
