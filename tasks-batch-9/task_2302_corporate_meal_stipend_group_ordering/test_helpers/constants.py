"""Domain thresholds and numeric constants from the PRD money pipeline."""

# --- §2.5 The Logical Clock -------------------------------------------------
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# --- §3.5 Stage one: line tax ----------------------------------------------
TAX_RATE = 0.0875

# --- §3.5 Stage two: fees ---------------------------------------------------
DELIVERY_FEE_BASE_CENTS = 599
FREE_DELIVERY_THRESHOLD_CENTS = 3500
SERVICE_FEE_RATE = 0.10
SERVICE_FEE_MIN_CENTS = 99
SERVICE_FEE_MAX_CENTS = 500
SERVICE_DISCOUNT_TIER_1_CENTS = 5000
SERVICE_DISCOUNT_TIER_2_CENTS = 12000
SERVICE_DISCOUNT_RATE_1 = 0.10
SERVICE_DISCOUNT_RATE_2 = 0.25

# --- §3.6 Group order consolidation ----------------------------------------
GROUP_DELIVERY_FEE_CENTS = 1250
GROUP_REOPEN_LIMIT = 2

# --- §3.5 Stage four: administration fee -----------------------------------
ADMIN_TIER_1_CENTS = 100_000
ADMIN_TIER_2_CENTS = 500_000
ADMIN_RATE_LOW = 0.05
ADMIN_RATE_MID = 0.04
ADMIN_RATE_HIGH = 0.03

# --- §3.7 Taxable benefit accrual ------------------------------------------
DE_MINIMIS_PER_MEAL_CENTS = 2000
IMPUTED_REPORTING_THRESHOLD_CENTS = 1000

# --- §2.3 Pagination --------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100

# --- §3.1 Program defaults --------------------------------------------------
DEFAULT_MAX_DELIVERY_RADIUS_KM = 8.0
DEFAULT_ROLLOVER_CAP_PCT = 0.25
DEFAULT_DOCK_BUFFER_MINUTES = 15
DEFAULT_MAX_CONCURRENT_GROUP_DELIVERIES = 1

# --- §3.2 Eligible window / weekday defaults used by the test corpus -------
LUNCH_WINDOW_START_MINUTE = 660   # 11:00 UTC
LUNCH_WINDOW_END_MINUTE = 840     # 14:00 UTC, exclusive
WEEKDAYS_MON_TO_FRI = [1, 2, 3, 4, 5]

# --- Convenient instants (all Mondays / weekdays in August 2026) -----------
MONDAY_2026_08_03 = "2026-08-03T00:00:00Z"
MONDAY_NOON = "2026-08-03T12:00:00Z"          # minute-of-day 720
TUESDAY_NOON = "2026-08-04T12:00:00Z"
WEDNESDAY_NOON = "2026-08-05T12:00:00Z"
SATURDAY_NOON = "2026-08-08T12:00:00Z"        # ISO weekday 6
WINDOW_START_INSTANT = "2026-08-03T11:00:00Z"  # minute-of-day 660
WINDOW_LAST_INSTANT = "2026-08-03T13:59:00Z"   # minute-of-day 839
WINDOW_END_INSTANT = "2026-08-03T14:00:00Z"    # minute-of-day 840, refused

TEST_DEFAULTS = {
    "EMPLOYER_NAME": "Acme Corp",
    "BILLING_ACCOUNT_REF": "ACCT-ACME-1",
    "CUISINE": "THAI",
    "PER_MEAL_CAP_CENTS": 2500,
    "DAILY_MEAL_LIMIT": 1,
    "MONTHLY_ALLOCATION_CENTS": 50_000,
    "PERIOD_MONTH": "2026-08",
    "HEADCOUNT_PLANNED": 2,
    "LINE_UNIT_PRICE_CENTS": 1000,
}
