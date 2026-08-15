"""Domain thresholds and pinned arithmetic constants from PRD §2-§3."""

# --- Logical clock (PRD §2.7) ---
CLOCK_START_ISO = "2026-08-01T00:00:00Z"

# --- Date hold TTL ladder (PRD §3.2) ---
HOLD_TTL_HOURS = {"P1": 48, "P2": 24, "COURTESY": 12}
CHALLENGE_WINDOW_HOURS = 24

# --- Booking lead time + schedule (PRD §3.2) ---
BOOKING_LEAD_DAYS = 7

# --- Deposit timing (PRD §3.3) ---
DEPOSIT_LEAD_DAYS = 14

# --- Cancellation policy (PRD §3.9) ---
PENALTY_TIERS_DAYS = (60, 30, 14, 7)  # >=60:0.00, >=30:0.25, >=14:0.50, >=7:0.75, else 1.00
LOW_SALES_KILL_FEE_PCT = 0.50
SUPPORT_KILL_FEE_PCT = 0.50
LOW_SALES_THRESHOLD_PCT = 0.30

# --- Deal term bounds (PRD §3.3) ---
MAX_ARTIST_SPLIT_PCT = 1.0
MAX_BAR_SPLIT_PCT = 0.25
MAX_MERCH_SPLIT_PCT = 0.30
MAX_DEPOSIT_PCT = 0.5

# --- Pagination (PRD §2.3) ---
DEFAULT_PAGE_LIMIT = 10
MAX_PAGE_LIMIT = 100

# --- Shared test defaults ---
TEST_DEFAULTS = {
    "ARTIST": {
        "legal_name": "Test Artist",
        "agency": "Test Agency",
        "guarantee_floor_cents": 10000,
        "deposit_pct": 0.25,
    },
    "AGENT": {
        "display_name": "Test Agent",
        "agency_name": "Test Agency",
    },
    "OFFER": {
        "deal_kind": "FLAT_GUARANTEE",
        "guarantee_cents": 100000,
        "artist_split_pct": 0.0,
        "versus_threshold_cents": 0,
        "expense_budget_cents": 10000,
        "support_budget_cents": 0,
        "bar_split_pct": 0.10,
        "merch_split_pct": 0.20,
    },
    "TIER": {
        "tier_name": "GA",
        "face_price_cents": 2000,
        "capacity": 100,
        "tier_order": 1,
    },
}
