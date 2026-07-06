"""Domain thresholds — numeric constants from the PRD calculations (§3)."""

# Pricing (§3.2)
GRATUITY_PCT = 0.18
SERVICE_FEE_MIN_CENTS = 25000
SERVICE_FEE_MAX_CENTS = 200000
DEPOSIT_PCT = 0.5
# Tiered service-fee percentages by guest count.
SERVICE_FEE_TIER_SMALL_PCT = 0.20   # guest_count <= 50
SERVICE_FEE_TIER_MID_PCT = 0.18     # 51..150
SERVICE_FEE_TIER_LARGE_PCT = 0.15   # > 150

# BYOB inventory (§3.6)
BEER_RATIO = 0.40
WINE_RATIO = 0.30
SERVINGS_PER_BEER_UNIT = 1
SERVINGS_PER_WINE_BOTTLE = 5
SERVINGS_PER_SPIRIT_BOTTLE = 16
ICE_LBS_PER_GUEST = 1.5
GLASSWARE_PER_GUEST = 2.5

# Labor (§3.5)
OT_THRESHOLD_HOURS = 8
OT_MULTIPLIER = 1.5

# Reliability (§3.5)
NO_SHOW_PENALTY_STRICT = 15
CANCEL_PENALTY_STRICT = 5
NO_SHOW_PENALTY_LENIENT = 8
LEAD_MIN_STRICT_SCORE = 70

# Breakage (§3.9)
BREAKAGE_ALLOWANCE_PCT = 0.02
REPLACEMENT_COST_PER_ITEM_CENTS = 500

# Cancellation (§3.8)
CANCEL_FEE_PCT = 0.5

# Temporal windowing (§2.9) — bartender travel buffer, in minutes.
TRAVEL_BUFFER_MINUTES = 90

# Canonical CLASSIC package + 80-guest / 5h event figures used across the
# design indices (all values PRD-derivable; kept here for test convenience).
CLASSIC_80G_5H = {
    "subtotal_cents": 229000,
    "service_fee_cents": 41220,
    "gratuity_cents": 41220,
    "final_grand_total_cents": 311440,
    "provisional_grand_total_cents": 277440,
    "deposit_due_cents": 138720,
    "billable_hours": 5,
    "required_bartender_count": 2,
}
