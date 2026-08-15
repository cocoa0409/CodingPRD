"""Domain thresholds — numeric constants named by the PRD workflows."""

# Logical clock (PRD §2.4): the clock reads exactly this instant until set.
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

# Certifications (PRD §3.2): a PASSED certification lives 180 days.
CERT_VALID_DAYS = 180

# Habitability scoring (PRD §3.6)
WEIGHT_CRITICAL = 25
WEIGHT_MAJOR = 10
WEIGHT_MINOR = 3
HOLD_THRESHOLD = 40

# Utility overage pricing (PRD §3.5)
ALLOWANCE_UNITS = {"ELECTRIC": 200, "GAS": 100, "WATER": 150}
TIER1_SPAN = 100
TIER1_RATE_CENTS = 12.5
TIER2_RATE_CENTS = 18.75

# Subsidy tiers (PRD §3.4)
TIER_HIGH_THRESHOLD = 0.50
TIER_HIGH_CREDIT = 0.30
TIER_LOW_THRESHOLD = 0.30
TIER_LOW_CREDIT = 0.15

# Payroll deduction cap (PRD §3.5)
FEDERAL_MAX_PCT = 0.30
MIN_NET_WAGE_FLOOR_CENTS = 40000

# Delinquency (PRD §3.5)
GRACE_DAYS = 10

# Season windows (PRD §3.1)
MAINTENANCE_GAP_DAYS = 14

# Complaints (PRD §3.7)
SLA_HOURS = 72

# Common test data
TEST_DEFAULTS = {
    "STATE_CODE": "CA",
    "UNIT_TYPE": "FAMILY_UNIT",
    "MAX_OCCUPANCY": 4,
    "MONTHLY_RENT_CENTS": 90000,
    "DORM_RENT_CENTS": 62000,
    "HOUSEHOLD_INCOME_CENTS": 6000000,
    "MOVE_IN_DATE": "2026-08-11",
    "WINDOW_OPEN": "2026-08-01",
    "WINDOW_CLOSE": "2026-11-30",
}
