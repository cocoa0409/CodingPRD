"""Domain thresholds — numeric constants pinned by the PRD."""
from __future__ import annotations


# Cancellation refund tiers (PRD §3.6).
FREE_CANCEL_LEAD_MINUTES = 1440           # 24 hours
LATE_CANCEL_LEAD_MINUTES = 120            # 2 hours
LATE_CANCEL_PAID_REFUND_BPS = 5000        # 50% of paid_amount_cents

# Match deadline / quorum (PRD §3.7).
MATCH_CUTOFF_MINUTES = 60                 # match_deadline_at = starts_at - 60 min
DEPOSIT_HOLD_TTL_MINUTES = 15             # promoted booking must confirm within 15 min

# Spam scoring (PRD §3.9).
SHORT_COMMENT_THRESHOLD = 50
REPEAT_REVIEW_THRESHOLD = 3
SCORE_SPREAD_THRESHOLD = 3
SPAM_SIGNAL_SOFT = 2
SPAM_SIGNAL_HARD_BLOCK = 4
MAX_MODERATION_ROUNDS = 3

# Pagination (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_DEFAULT_OFFSET = 0
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100

# BPS arithmetic (PRD §2.10).
BPS_TOTAL = 10000

# Test default values used across factories.
TEST_DEFAULTS = {
    "venue_name": "Test Venue",
    "venue_chain_id": "test-chain",
    "deposit_policy_cents": 2000,
    "revenue_share_bps": 4500,
    "author_royalty_bps": 2000,
    "host_commission_bps": 1500,
    "platform_fee_bps": 2000,
    "timezone": "UTC",
    # Standard business hours: open 09:00, close 23:00 every day.
    "business_hours": {
        str(d): {"open": "09:00", "close": "23:00"} for d in range(7)
    },
    "room_capacity_min": 2,
    "room_capacity_max": 8,
    "room_turnover_minutes": 30,
    "theme_genre": "MYSTERY",
    "theme_difficulty": "MEDIUM",
    "theme_duration_minutes": 90,
    "theme_min_players": 2,
    "theme_max_players": 4,
    "theme_base_price_cents": 5000,
    "player_age": 30,
    "staff_max_weekly_minutes": 2400,
}
