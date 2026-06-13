"""Domain thresholds — numeric constants from the PRD's calculations (§3)."""

# ─── Group-discount tiers (PRD §3.3) ─────────────────────────────────────
GROUP_DISCOUNT = {
    "TIER_SMALL_PCT": 5,     # [min_group_size, 8)  -> 5%
    "TIER_MID_PCT": 10,      # [8, 15)              -> 10%
    "TIER_LARGE_PCT": 15,    # [15, +inf)           -> 15%
    "TIER_MID_MIN": 8,
    "TIER_LARGE_MIN": 15,
    "DEFAULT_MIN_GROUP_SIZE": 5,
}

# ─── Insurance per-traveler rates (PRD §3.4) ─────────────────────────────
INSURANCE_RATES = {
    "BASIC_RATE_CENTS": 1500,      # $15 per traveler, non-refundable
    "PREMIUM_RATE_CENTS": 4000,    # $40 per traveler, refundable
}

# ─── Cancellation penalty tiers (PRD §3.7) ───────────────────────────────
CANCELLATION_PENALTY = {
    "TIER_FREE_MIN_DAYS": 60,
    "TIER_LOW_MIN_DAYS": 30,
    "TIER_HIGH_MIN_DAYS": 7,
    "TIER_LOW_PCT": 25,
    "TIER_HIGH_PCT": 50,
    "TIER_FULL_PCT": 100,
}

# ─── Component overlap buffer (PRD §3.5) ─────────────────────────────────
OVERLAP = {
    "BUFFER_SECONDS": 7200,   # 2-hour turnaround buffer for FLIGHT/ACTIVITY
}

# ─── Package defaults (PRD §3.2) ─────────────────────────────────────────
PACKAGE_DEFAULTS = {
    "DEPOSIT_PCT": 20,
    "BALANCE_DUE_DAYS_BEFORE_DEPARTURE": 30,
    "MIN_GROUP_SIZE_FOR_DISCOUNT": 5,
}

# ─── Pagination defaults (PRD §2.3) ──────────────────────────────────────
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}
