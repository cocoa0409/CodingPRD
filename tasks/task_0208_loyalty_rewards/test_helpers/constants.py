"""Domain thresholds and canonical config for the Loyalty Rewards API.

These mirror the program-wide economic policy and the canonical tier ladder
used throughout the test suite. GOLD_RANK is the rank at and above which the
catalog tier discount applies (per PRD Section 3.7).
"""

# Canonical program-wide economic policy (PRD Section 3.1).
PROGRAM_DEFAULTS = {
    "name": "P",
    "base_earn_rate": 1.0,
    "point_value_cents": 1.0,
    "lot_expiration_months": 12,
    "qualifying_window_months": 12,
    "birthday_reward_points": 200,
    "referral_referrer_points": 500,
    "referral_referee_points": 250,
    "referral_min_qualifying_cents": 10000,
}

# Canonical tier ladder. Each entry: code, qualify_threshold, earn_multiplier,
# transfer_ratio, rank.
TIER_STANDARD = {"code": "STANDARD", "qualify_threshold": 0, "earn_multiplier": 1.0, "transfer_ratio": 0.5, "rank": 0}
TIER_SILVER = {"code": "SILVER", "qualify_threshold": 2000, "earn_multiplier": 1.25, "transfer_ratio": 0.6, "rank": 1}
TIER_GOLD = {"code": "GOLD", "qualify_threshold": 5000, "earn_multiplier": 1.5, "transfer_ratio": 0.8, "rank": 2}
TIER_PLATINUM = {"code": "PLATINUM", "qualify_threshold": 12000, "earn_multiplier": 2.0, "transfer_ratio": 1.0, "rank": 3}

# The rank assigned to GOLD; tier discount applies at this rank or higher.
GOLD_RANK = 2

# Pagination bounds (PRD Section 2.3).
PAGINATION = {"default_limit": 10, "min_limit": 1, "max_limit": 100, "min_offset": 0}
