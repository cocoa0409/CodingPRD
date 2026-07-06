"""Domain thresholds — numeric constants from the PRD pricing, financing, and
scheduling rules. Generic NON_EXISTENT_UUID comes from the framework."""

# --- System (acrylic) pricing: marginal area tiering ---
BASE_RATE_CENTS = {
    "SMOOTH_ACRYLIC": 3750,
    "TILE_LOOK_ACRYLIC": 5900,
    "STONE_LOOK_ACRYLIC": 8250,
}
TIER1_SQFT = 40
TIER2_SQFT = 40
TIER2_FACTOR = 0.90
TIER3_FACTOR = 0.80

# --- Accessibility add-on flat prices ---
ADDON_PRICE_CENTS = {
    "NONE": 0,
    "GRAB_BARS": 29900,
    "BARRIER_FREE_SHOWER": 249900,
    "WALK_IN_TUB": 449900,
}
# Add-ons that trigger a permit / accessible-crew requirement.
PERMIT_ADDONS = ("WALK_IN_TUB", "BARRIER_FREE_SHOWER")

# --- Promotions ---
PROMO_PCT = {"SPRING750": 0.075}

# --- Permit surcharge (tiered on net_price_cents) ---
SURCHARGE_TIER_THRESHOLD = 500000
PERMIT_FEE_LOW = 15000
PERMIT_FEE_HIGH = 30000

# --- Financing ---
DEPOSIT_PCT = 0.10
DTI_MAX_RATIO = 0.50
DTI_TIERS = [
    {"max": 0.20, "bps": 0},
    {"max": 0.35, "bps": 250},
    {"max": 0.50, "bps": 600},
]
PLAN = {
    "PLAN_12_0": {"apr_bps": 0, "term_months": 12, "min_amount_cents": 100000, "max_amount_cents": 1500000},
    "PLAN_60_999": {"apr_bps": 999, "term_months": 60, "min_amount_cents": 300000, "max_amount_cents": 5000000},
    "PLAN_120_1299": {"apr_bps": 1299, "term_months": 120, "min_amount_cents": 500000, "max_amount_cents": 8000000},
}

# --- Referral rewards ---
REFERRAL_FLAT_CENTS = 50000
REFERRAL_PCT = 0.03

# --- Scheduling ---
BUFFER_MINUTES = 60
MIN_LEAD_DAYS = 3

# --- Logical clock ---
CLOCK_START = "2026-05-01T00:00:00Z"

TEST_DEFAULTS = {
    "AREA": 100.0,
    "STATE_CODE": "CA",
    "INSTALL_DATE": "2026-06-01T00:00:00Z",
}
