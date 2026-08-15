"""Domain thresholds and shared fixtures data — numeric constants named in the PRD."""

# --- logical clock (PRD §2.5) ---
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

# --- valuation (PRD §3.3) ---
COMP_WINDOW_MONTHS = 24
RECENCY_WINDOW_MONTHS = 12
RECENCY_DISCOUNT = 0.97
TILLABLE_BASE = 0.85
TILLABLE_SLOPE = 0.30

# --- packaging reserve floor (PRD §3.2) ---
RESERVE_FLOOR_RATIO = 0.85

# --- bid increments (PRD §3.6) ---
TIER1_MAX = 100000
TIER2_MAX = 500000
TIER3_MAX = 1000000
INC1 = 1000
INC2 = 2500
INC3 = 5000
INC4 = 10000
COMBO_PREMIUM_PCT = 0.05

# --- earnest money (PRD §3.7) ---
EMD_PCT = 0.03
EMD_FLOOR = 10000
EMD_DUE_HOURS = 48
EMD_FORFEIT_GRACE_HOURS = 24

# --- commission (PRD §3.8) ---
COMMISSION_FLOOR = 7500
KICKER_THRESHOLD = 1.10
KICKER_PCT = 0.005

# --- closing costs (PRD §3.8) ---
TITLE_FLAT = 1500
TITLE_PCT = 0.002
SURVEY_PER_TRACT = 1200
ESCROW_PCT = 0.001
ESCROW_SELLER_SHARE = 0.5
EST_COST_PCT = 0.005

# --- auction scheduling (PRD §3.5) ---
AUCTION_MIN_DURATION_MINUTES = 60
AUCTION_MIN_LEAD_HOURS = 24
AUCTIONEER_BUFFER_HOURS = 2

# --- standard comparable-sale payloads reused across setups ---
# With the default clock 2026-08-01T00:00:00Z, all three fall inside the
# trailing 24-month eligibility window and share state_code "IA".
IA_COMPARABLE_C1 = {
    "county": "Dallas",
    "state_code": "IA",
    "sale_date": "2026-01-15T00:00:00Z",
    "sale_price_total": 900000,
    "gross_acres": 100,
    "tillable_acres": 95,
    "soil_productivity_index": 80,
}
IA_COMPARABLE_C2 = {
    "county": "Dallas",
    "state_code": "IA",
    "sale_date": "2025-09-01T00:00:00Z",
    "sale_price_total": 780000,
    "gross_acres": 120,
    "tillable_acres": 60,
    "soil_productivity_index": 65,
}
IA_COMPARABLE_C3 = {
    "county": "Polk",
    "state_code": "IA",
    "sale_date": "2024-09-01T00:00:00Z",
    "sale_price_total": 550000,
    "gross_acres": 100,
    "tillable_acres": 50,
    "soil_productivity_index": 55,
}
IA_COMPARABLES_TRIPLE = [IA_COMPARABLE_C1, IA_COMPARABLE_C2, IA_COMPARABLE_C3]

# Conventional timestamps used across setups (all relative to the default clock).
AUCTION_START = "2026-08-10T17:00:00Z"
AUCTION_END = "2026-08-10T19:00:00Z"
QUALIFICATION_EXPIRY = "2026-09-01T00:00:00Z"
TARGET_CLOSING_DATE = "2026-09-01T00:00:00Z"
