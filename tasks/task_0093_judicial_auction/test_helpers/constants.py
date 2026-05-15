"""Domain thresholds and numeric constants from the PRD.

All amounts are pinned to integer cents per PRD §2.5; percentages are
in basis points where 10000 = 100%.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Starting price calc (PRD §3.3)
# ---------------------------------------------------------------------------
FIRST_AUCTION_DISCOUNT_BPS = 3000      # 30% discount on first auction
REAUCTION_DISCOUNT_BPS = 2000          # 20% per re-auction round
MAX_AUCTION_ROUNDS = 3                 # Lot.round_number cap


# ---------------------------------------------------------------------------
# Deposit calc (PRD §3.4)
# ---------------------------------------------------------------------------
DEPOSIT_MIN_PERCENT_BPS = 500          # 5% lower bound on PERCENT mode
DEPOSIT_MAX_PERCENT_BPS = 3000         # 30% upper bound on PERCENT mode


# ---------------------------------------------------------------------------
# Bid increment ladder (PRD §3.5)
# ---------------------------------------------------------------------------
TIER_1_MAX_CENTS = 50_000_000          # < 500,000.00
TIER_2_MAX_CENTS = 200_000_000         # < 2,000,000.00
TIER_3_MAX_CENTS = 1_000_000_000       # < 10,000,000.00
INC_TIER_1_CENTS = 100_000             # 1,000.00
INC_TIER_2_CENTS = 500_000             # 5,000.00
INC_TIER_3_CENTS = 1_000_000           # 10,000.00
INC_TIER_4_CENTS = 5_000_000           # 50,000.00


# ---------------------------------------------------------------------------
# Soft-close window (PRD §3.5) — defaults per PRD §3.5 "default to three
# hundred (that is, five minutes)"
# ---------------------------------------------------------------------------
SOFT_CLOSE_WINDOW_SECONDS_DEFAULT = 300
SOFT_CLOSE_EXTENSION_SECONDS_DEFAULT = 300


# ---------------------------------------------------------------------------
# Anti-collusion (PRD §3.6)
# ---------------------------------------------------------------------------
W_SHARED_IP = 40
W_ALTERNATING = 30
W_IDENTICAL_INC = 20
W_YOUNG_ACCOUNT = 10
YOUNG_ACCOUNT_DAYS = 30
COLLUSION_SUSPECT_THRESHOLD = 60       # ACTIVE → SUSPENDED if score in [60, 79]
COLLUSION_BLOCK_THRESHOLD = 80         # → BLOCKED at >= 80


# ---------------------------------------------------------------------------
# Late-payment penalty (PRD §3.9)
# ---------------------------------------------------------------------------
DAILY_PENALTY_BPS = 50                 # 0.50% per calendar day
MAX_PENALTY_BPS = 1000                 # 10% cap
PENALTY_CAP_DAYS = 20                  # day 20 is when linear == cap
GRACE_FORFEITURE_DAYS = 7              # PRD §3.9: "more than seven days"
GRACE_EXTENSION_MIN_DAYS = 1
GRACE_EXTENSION_MAX_DAYS = 14


# ---------------------------------------------------------------------------
# Refund SLA (PRD §3.5, §3.10): "current instant plus seventy-two hours"
# ---------------------------------------------------------------------------
REFUND_SLA_HOURS = 72


# ---------------------------------------------------------------------------
# Statutory notice (PRD §3.1): "at least fifteen calendar days"
# ---------------------------------------------------------------------------
STATUTORY_NOTICE_DAYS = 15


# ---------------------------------------------------------------------------
# Transfer-handover spacing (PRD §3.11): "at least four hours apart"
# ---------------------------------------------------------------------------
HANDOVER_BUFFER_HOURS = 4


# ---------------------------------------------------------------------------
# Time conversion
# ---------------------------------------------------------------------------
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = 86400


# ---------------------------------------------------------------------------
# Defaults for fixture overrides
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "ASSESSMENT_VALUE_CENTS": 100_000_000,        # 1,000,000.00
    "FIXED_DEPOSIT_CENTS": 5_000_000,             # 50,000.00
    "PERCENT_DEPOSIT_BPS": 1000,                  # 10%
    "PAYMENT_DEADLINE_DAYS": 30,
    "AUCTION_DURATION_SECONDS": 3600,             # 1h
    "INSPECTION_DURATION_SECONDS": 14400,         # 4h
}


# Counterpart-agency map (PRD §3.11)
ASSET_PROFILE_TO_AGENCY = {
    "REAL_ESTATE": "REAL_ESTATE_REGISTRY",
    "VEHICLE": "VEHICLE_AUTHORITY",
    "EQUITY": "EQUITY_REGISTRY",
    "MOVABLE_ASSET": "COURT_BAILIFF",
}


__all__ = [
    "FIRST_AUCTION_DISCOUNT_BPS",
    "REAUCTION_DISCOUNT_BPS",
    "MAX_AUCTION_ROUNDS",
    "DEPOSIT_MIN_PERCENT_BPS",
    "DEPOSIT_MAX_PERCENT_BPS",
    "TIER_1_MAX_CENTS",
    "TIER_2_MAX_CENTS",
    "TIER_3_MAX_CENTS",
    "INC_TIER_1_CENTS",
    "INC_TIER_2_CENTS",
    "INC_TIER_3_CENTS",
    "INC_TIER_4_CENTS",
    "SOFT_CLOSE_WINDOW_SECONDS_DEFAULT",
    "SOFT_CLOSE_EXTENSION_SECONDS_DEFAULT",
    "W_SHARED_IP",
    "W_ALTERNATING",
    "W_IDENTICAL_INC",
    "W_YOUNG_ACCOUNT",
    "YOUNG_ACCOUNT_DAYS",
    "COLLUSION_SUSPECT_THRESHOLD",
    "COLLUSION_BLOCK_THRESHOLD",
    "DAILY_PENALTY_BPS",
    "MAX_PENALTY_BPS",
    "PENALTY_CAP_DAYS",
    "GRACE_FORFEITURE_DAYS",
    "GRACE_EXTENSION_MIN_DAYS",
    "GRACE_EXTENSION_MAX_DAYS",
    "REFUND_SLA_HOURS",
    "STATUTORY_NOTICE_DAYS",
    "HANDOVER_BUFFER_HOURS",
    "SECONDS_PER_HOUR",
    "SECONDS_PER_DAY",
    "TEST_DEFAULTS",
    "ASSET_PROFILE_TO_AGENCY",
]
