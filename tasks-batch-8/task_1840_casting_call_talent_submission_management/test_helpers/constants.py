"""Domain thresholds and numeric constants from the PRD's calculation rules.

PRD section 2.6 / 3.7 / 3.8 / 3.9 pin these values:
- five workdays per union week (fee proration daily-rate divisor)
- guarantee cap of fifty-two times the weekly rate
- cancellation penalty tier boundaries (14 / 7 / 3 days; 0/25/50/100 percent)
- union eligibility threshold of 3 engagements in a 365-day window
- standard engagement day of 8 requested hours (minor daily-hours cap)
- self-tape duration bound (0, 600] seconds
"""

# Logical clock
STARTUP_CLOCK = "2026-08-01T00:00:00Z"  # PRD 2.4: startup default, never wall-clock

# Fee proration (PRD 2.6, 3.7)
WORKDAYS_PER_WEEK = 5
GUARANTEE_WEEKS_CAP = 52

# Cancellation penalty tiers (PRD 3.9); boundaries inclusive at the lower bound
TIER_FULL_NOTICE_DAYS = 14   # >= 14 days out -> 0%
TIER_HIGH_NOTICE_DAYS = 7    # 7..13 -> 25%
TIER_LOW_NOTICE_DAYS = 3     # 3..6 -> 50%
PCT_FULL_NOTICE = 0
PCT_HIGH_NOTICE = 25
PCT_LOW_NOTICE = 50
PCT_LATE = 100

# Union eligibility (PRD 3.9)
UNION_THRESHOLD = 3          # "reaches at least three"
UNION_WINDOW_DAYS = 365

# Minor daily hours (PRD 3.8)
STANDARD_DAY_HOURS = 8

# Self-tape duration bound (PRD 3.4): must exceed zero and not exceed 600
TAPE_MAX_DURATION_SECONDS = 600

# Taft-Hartley filing window (PRD 3.9): confirmed_at + 15 calendar days
TAFT_HARTLEY_FILING_DAYS = 15

# Shared test defaults
TEST_DEFAULTS = {
    "WEEKLY_RATE_CENTS": 1_000_000,
    "GUARANTEE_CENTS": 800_000,
    "BREAKDOWN_RATE_CENTS": 1_000_000,
    "SESSION_CAPACITY": 4,
    "ADULT_DOB": "1990-01-01T00:00:00Z",
    "MINOR_DOB": "2012-01-01T00:00:00Z",
    "PRODUCTION_START": "2026-08-01T00:00:00Z",
    "PRODUCTION_WRAP": "2026-09-30T00:00:00Z",
    "SUBMISSION_DEADLINE": "2026-09-01T00:00:00Z",
    "OFFER_EXPIRES": "2026-08-20T00:00:00Z",
    "SETUP_CLOCK": "2026-08-03T00:00:00Z",
}
