"""Domain thresholds — numeric constants from the PRD's calculation rules (§2.4, §3.2)."""

# Logical clock startup default (PRD §2.4): before any set_current_utc call,
# the clock stands at exactly this instant and never falls back to wall-clock.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Discount matrix (PRD §3.2): half-open share bands; top band closed at 100.
DISCOUNT_BAND_EDGES = [0, 1, 20, 35, 50, 75, 100]
DISCOUNT_MATRIX = {
    "CATEGORY_ONE": {"URBAN": [20, 40, 50, 60, 80, 90], "RURAL": [25, 50, 60, 70, 80, 90]},
    "CATEGORY_TWO": {"URBAN": [20, 40, 50, 60, 80, 85], "RURAL": [25, 50, 60, 70, 80, 85]},
}
CEP_MULTIPLIER = 1.6
CEP_SHARE_CAP = 100.00

# Category Two budget pool (PRD §3.2).
C2_PER_STUDENT_CENTS = 16700
C2_PER_SQFT_CENTS = 450
C2_FLOOR_CENTS = 2500000

# Program calendar (PRD §2.4).
BID_WINDOW_DAYS = 28
APPEAL_WINDOW_DAYS = 60
INVOICE_WINDOW_DAYS = 120
RETENTION_YEARS = 10

# Standard dates used across scenarios.
DATES = {
    "CYCLE_LABEL": "FY2027",
    "WINDOW_OPEN": "2026-10-01",
    "WINDOW_CLOSE": "2027-03-31",
    "SERVICE_DELIVERY_DEADLINE": "2027-06-30",
    "BID_CLOCK": "2026-08-05T00:00:00Z",
    "CLOSE_CLOCK": "2026-08-29T00:00:00Z",
    "FILING_CLOCK": "2026-10-15T00:00:00Z",
    "DECISION_CLOCK": "2027-04-15T00:00:00Z",
    "CONTRACT_START": "2027-04-01",
    "CONTRACT_END": "2028-03-31",
}

# Common monetary test defaults (integer cents).
TEST_DEFAULTS = {
    "BID_PRICE_C1": 50000,
    "BID_PRICE_C2": 2000000,
    "STUDENT_COUNT": 1000,          # C2 cap 16,700,000
    "LIBRARY_SQUARE_FEET": 3000,    # computed 1,350,000 -> floor 2,500,000
    "SNAPSHOT_TOTAL": 1000,
    "SNAPSHOT_FREE": 300,           # direct share 30.00 -> band [20,35)
}
