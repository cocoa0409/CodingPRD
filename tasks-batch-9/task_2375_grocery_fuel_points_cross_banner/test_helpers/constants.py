"""Domain thresholds and pinned literals taken from the PRD's calculations."""

# --------------------------------------------------------------------------
# Banner configuration defaults (PRD §2.4) — every knob is optional and the
# defaults below are what a banner registered without overrides must carry.
# --------------------------------------------------------------------------
BANNER_DEFAULTS = {
    "base_points_per_dollar": 1,
    "gift_card_multiplier": 4,
    "pharmacy_multiplier": 2,
    "pharmacy_points_per_script": 50,
    "max_stacked_multiplier": 8,
    "max_stack_count": 2,
    "points_per_discount_block": 100,
    "cents_off_per_block": 10,
    "max_cents_off_per_gallon": 100,
    "owned_max_gallons_per_redemption": 35,
    "min_points_per_redemption": 100,
    "rollover_cap_points": 500,
    "max_transfers_per_cycle": 3,
    "expiry_basis": "LOT_FIFO",
    "fraud_scoring_mode": "INSTANTANEOUS",
    "freeze_threshold_score": 60,
}

# --------------------------------------------------------------------------
# Partner reimbursement pricing (PRD §3.6)
# --------------------------------------------------------------------------
SETTLEMENT = {
    "TIER_LOW_MAX_GALLONS": 500,
    "TIER_MID_MAX_GALLONS": 2000,
    "TIER_LOW_RATE": 0.85,
    "TIER_MID_RATE": 0.90,
    "TIER_HIGH_RATE": 0.95,
    "ADMIN_FEE_PCT": 0.015,
    "ADMIN_FEE_CAP_CENTS": 50000,
}

# --------------------------------------------------------------------------
# Fraud scoring (PRD §3.9)
# --------------------------------------------------------------------------
FRAUD = {
    "DECAY_PER_DAY": 0.05,
    "DECAY_FLOOR": 0.25,
    "OVERDRAWN_AUTH_WEIGHT": 40,
    "RAPID_TRANSFER_WEIGHT": 25,
    "MIN_SEVERITY_WEIGHT": 1,
    "MAX_SEVERITY_WEIGHT": 100,
}

# --------------------------------------------------------------------------
# Manual-adjustment authority ceilings (PRD §3.9)
# --------------------------------------------------------------------------
TIER_CEILINGS = {
    "TIER1": 500,
    "TIER2": 5000,
}

# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# --------------------------------------------------------------------------
# The logical clock (PRD §2.7) and the calendar the tests work in
# --------------------------------------------------------------------------
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"

MONTH_WINDOWS = {
    "2026-07": ("2026-07-01T00:00:00Z", "2026-07-31T23:59:59.999Z"),
    "2026-08": ("2026-08-01T00:00:00Z", "2026-08-31T23:59:59.999Z"),
    "2026-09": ("2026-09-01T00:00:00Z", "2026-09-30T23:59:59.999Z"),
    "2026-10": ("2026-10-01T00:00:00Z", "2026-10-31T23:59:59.999Z"),
    "2026-11": ("2026-11-01T00:00:00Z", "2026-11-30T23:59:59.999Z"),
}

MID_AUGUST = "2026-08-05T10:00:00Z"

TEST_DEFAULTS = {
    "GROCERY_CENTS_PER_POINT": 100,  # a GROCERY line of N*100 cents earns N points
    "PARTNER_PER_GALLON_CAP_CENTS": 30,
    "PARTNER_MAX_GALLONS_PER_REDEMPTION": 20,
}
