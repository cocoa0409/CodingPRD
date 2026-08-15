"""Domain thresholds and canonical fixture values (PRD business rules)."""

# --- Hold/sell recommendation hysteresis band (PRD Asset Registration) ---
SELL_BAND_NUM = 105
HOLD_BAND_NUM = 95
BAND_DEN = 100

# --- Bidder qualification (PRD Bidder Registration) ---
QUALIFY_PCT = 25

# --- Deposit schedule (PRD Purchase Agreement execution) ---
INITIAL_BPS = 300
ADDITIONAL_BPS = 200
MIN_DEPOSIT_CENTS = 10_000_000
INITIAL_DEPOSIT_DUE_DAYS = 3

# --- Retrade caps (PRD Due Diligence / Retrade Defense) ---
RETRADE_ITEM_CAP_BPS = 200
RETRADE_AGGREGATE_CAP_BPS = 500

# --- Tiered broker commission (PRD Broker Engagements) ---
TIER1_CAP = 1_500_000_000
TIER2_CAP = 3_000_000_000
TIER1_BPS = 200
TIER2_BPS = 150
TIER3_BPS = 100
MIN_FEE_CENTS = 25_000_000

# --- Loan exit (PRD Loan Exit) ---
YM_FLOOR_BPS = 100
ACCRUAL_BASIS_DAYS = 360
QUOTE_VALIDITY_DAYS = 10

# --- Closing statement waterfall (PRD Closing Statements) ---
HOLDBACK_BPS = 50
MIN_HOLDBACK_CENTS = 1_000_000
ACTUAL_YEAR_DAYS = 365
BANKERS_YEAR_DAYS = 360
BANKERS_MONTH_DAYS = 30

# --- Escrow (PRD Post-Closing Escrow) ---
ESCROW_RELEASE_DAYS = 365

# --- Relist cooling gap (PRD Listing / Call for Offers) ---
RELIST_COOLING_DAYS = 7

# --- Data-room document categories used by setup chains ---
DOCUMENT_CATEGORIES = [
    "RENT_ROLL",
    "OPERATING_STATEMENTS",
    "TITLE_COMMITMENT",
    "SURVEY",
    "ENVIRONMENTAL_REPORT",
    "LEASES",
    "TAX_BILLS",
    "SERVICE_CONTRACTS",
]

# --- Due-diligence categories (PRD Due Diligence) ---
DD_CATEGORIES = ["PHYSICAL", "FINANCIAL", "LEGAL", "ENVIRONMENTAL", "TITLE"]

# --- Canonical logical-clock waypoints used across setup chains ---
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
ENGAGEMENT_WINDOW_START = "2026-08-10T00:00:00Z"
ENGAGEMENT_WINDOW_END = "2027-02-10T00:00:00Z"
OFFERS_DEADLINE = "2026-09-15T00:00:00Z"
CLOCK_AFTER_DEADLINE = "2026-09-16T00:00:00Z"
CLOSING_DATE_ALPHA = "2026-10-30T00:00:00Z"
CLOSING_DATE_DELTA = "2026-10-15T00:00:00Z"
CLOCK_PAST_DD_30 = "2026-10-17T00:00:00Z"
CLOCK_PAST_DD_20 = "2026-10-07T00:00:00Z"
TAX_PERIOD_START = "2026-01-01T00:00:00Z"
