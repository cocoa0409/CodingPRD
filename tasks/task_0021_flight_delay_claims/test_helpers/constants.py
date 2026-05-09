"""Domain thresholds — numeric constants from PRD §3.6 and §3.7."""

# --- Tier table (PRD §3.6) ---
# "When delay_minutes_used is at least 360 minutes (or equals the infinity
#  sentinel), tier_selected is TIER_C and the tier amount is 60,000 cents..."
TIER_A_MIN_MINUTES = 60
TIER_B_MIN_MINUTES = 180
TIER_C_MIN_MINUTES = 360

TIER_A_AMOUNT_CENTS = 10000   # €100
TIER_B_AMOUNT_CENTS = 25000   # €250
TIER_C_AMOUNT_CENTS = 60000   # €600

# --- Sentinels (PRD §3.6) ---
# "delay_minutes_used takes the infinity sentinel value of 99,999,999"
INFINITY_DELAY_SENTINEL = 99_999_999

# --- Reinsurance waterfall (PRD §3.7) ---
# "primary retention (set at 50,000 cents, i.e., five hundred euros)" and
# "reinsurer cap (set at 30,000 cents, i.e., three hundred euros)"
PRIMARY_RETENTION_CENTS = 50000
REINSURER_LAYER_CENTS = 30000

# --- Multi-source flight quorum window (PRD §2.7) ---
# "that window has a length of 30 minutes"
QUORUM_WINDOW_MS = 30 * 60 * 1000   # 1_800_000
MIN_SOURCES_FOR_QUORUM = 2

# --- Auto-active boundary (PRD §3.2) ---
# "when Insurer.now_epoch_ms is at least scheduled_departure_epoch_ms - 1800000"
AUTO_ACTIVE_PRE_DEPARTURE_MS = 30 * 60 * 1000

# --- Archive eligibility (PRD §3.2) ---
ARCHIVE_AGE_THRESHOLD_MS = 90 * 24 * 60 * 60 * 1000   # 90 days

# --- Basis points denominator (PRD §3.6) ---
# "basis points are out of ten thousand"
BPS_DENOMINATOR = 10000

# --- Pagination (PRD §2.3) ---
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# --- Test defaults (used by factories) ---
DEFAULT_CURRENCY = "EUR"
DEFAULT_DEDUCTIBLE_CENTS = 2500          # €25
DEFAULT_POLICY_LIMIT_CENTS = 150000      # €1500
DEFAULT_QUOTA_TOTAL_CENTS = 10_000_000   # €100,000
