"""Domain thresholds and default configuration values (PRD §2.6, §3.1)."""
import copy

# Logical clock startup default (PRD §2.6).
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"

# Standard fair deadlines used across scenarios.
OWNERSHIP_DEADLINE = "2026-06-01T00:00:00Z"
POSSESSION_DEADLINE = "2026-06-15T00:00:00Z"
DEFAULT_OWNERSHIP_ACQUIRED = "2026-04-01T00:00:00Z"
DEFAULT_POSSESSION_START = "2026-05-01T00:00:00Z"
DEFAULT_WEIGHED_AT = "2026-07-01T10:00:00Z"

# Judge spacing rule (PRD §3.4): at least a 15-minute gap between assignments.
JUDGE_MIN_GAP_MINUTES = 15
# Reoffer bound (PRD §3.6): reoffer allowed only while reoffer_count is below 2.
MAX_REOFFER_COUNT = 2

DEFAULT_PREMIUM_SCHEDULE = {
    "MARKET_STEER": {
        "grand_champion_cents": 50000, "reserve_champion_cents": 30000,
        "rank_1_cents": 12000, "rank_2_cents": 10000, "rank_3_cents": 8000,
        "other_rank_cents": 4000,
    },
    "MARKET_SWINE": {
        "grand_champion_cents": 40000, "reserve_champion_cents": 24000,
        "rank_1_cents": 10000, "rank_2_cents": 8000, "rank_3_cents": 6000,
        "other_rank_cents": 3000,
    },
    "MARKET_LAMB": {
        "grand_champion_cents": 30000, "reserve_champion_cents": 20000,
        "rank_1_cents": 9000, "rank_2_cents": 7000, "rank_3_cents": 5000,
        "other_rank_cents": 2500,
    },
    "MARKET_GOAT": {
        "grand_champion_cents": 30000, "reserve_champion_cents": 20000,
        "rank_1_cents": 9000, "rank_2_cents": 7000, "rank_3_cents": 5000,
        "other_rank_cents": 2500,
    },
}

DEFAULT_STATE_QUALIFY_RANK = {
    "MARKET_STEER": 2, "MARKET_SWINE": 2, "MARKET_LAMB": 2, "MARKET_GOAT": 2,
}

DEFAULT_SALE_RANK_THRESHOLD = {
    "MARKET_STEER": 3, "MARKET_SWINE": 3, "MARKET_LAMB": 3, "MARKET_GOAT": 3,
}

DEFAULT_SPECIES_SALE_ORDER = [
    "MARKET_STEER", "MARKET_SWINE", "MARKET_LAMB", "MARKET_GOAT",
]

TEST_DEFAULTS = {
    "PREMIUM_BUDGET_CENTS": 100000,
    "COMMISSION_RATE": 0.05,
    "BUYER_PREMIUM_RATE": 0.03,
    "YARDAGE_FEE_CENTS": 1500,
    "PREMIUM_CAP_CENTS": 60000,
    "CREDIT_LIMIT_CENTS": 200000,
}


def default_premium_schedule():
    return copy.deepcopy(DEFAULT_PREMIUM_SCHEDULE)
