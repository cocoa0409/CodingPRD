"""Domain thresholds and shared values (PRD §2, §3)."""

# Logical clock starts here on every fresh server (PRD §2.4).
CLOCK_START = "2026-08-01"

# Channels in the fixed creation order used at sheet scheduling time (PRD §2.8).
CHANNEL_ORDER = ["BRANCH", "ONLINE", "MOBILE", "CALL_CENTER"]

# Rate arithmetic (PRD §2.6, §3.5): integer bp; accrual in milli-cents; the
# per-day accrual divides balance_cents * current_rate_bp by 3,650 (365-day
# year times the basis-point denominator) and floors to whole milli-cents.
ACCRUAL_DIVISOR = 3650
MILLI_PER_CENT = 1000

# Adverse-change notice threshold (PRD §2.9): drops of ten basis points or more.
ADVERSE_DROP_BP = 10
# RATE_CHANGE_ADVERSE notices are due five days after the triggering date (PRD §2.9).
ADVERSE_NOTICE_DUE_DAYS = 5
# PROMO_EXPIRY notices are created thirty days before promo_end_date (PRD §2.9).
PROMO_EXPIRY_NOTICE_DAYS = 30

# Exception authority ladder (PRD §3.6): BRANCH at delta <= 25, COMMITTEE for
# 26..75 inclusive, and a delta above 75 is rejected at creation.
AUTHORITY_BRANCH_MAX_DELTA_BP = 25
AUTHORITY_COMMITTEE_MAX_DELTA_BP = 75
# APPROVED-but-never-applied exception requests expire once logical today is
# more than thirty days past the decision date (PRD §3.6).
APPROVED_APPLY_WINDOW_DAYS = 30

# Default RepricingCycle cadence auto-created with a pair's first sheet (PRD §3.1).
DEFAULT_CADENCE_DAYS = 30

# Open-ended sheet window sentinel (PRD §2.8).
OPEN_ENDED_DATE = "9999-12-31"

TEST_DEFAULTS = {
    "MARKET": "US-WEST",
    "EFFECTIVE_DATE": "2026-08-15",
    "DISCLOSURE_LEAD_DAYS": 7,
    "MARGIN_FLOOR_BP": 0,
    "RATE_CAP_BP": 500,
    "CD_RATE_CAP_BP": 900,
}
