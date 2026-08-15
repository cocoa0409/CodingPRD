"""Domain thresholds and pricing constants from the PRD's calculation rules."""

# License fee quote (PRD §3.5): scope multiplier, then territory, then exclusivity,
# then the reuse discount; rounding happens once at the final step.
SCOPE_MULTIPLIER = {"PRINT": 1.0, "DIGITAL": 1.2, "SOCIAL": 0.8, "SYNDICATION": 1.5}
TERRITORY_MULTIPLIER = {"DOMESTIC": 1.0, "INTERNATIONAL": 1.3, "GLOBAL": 1.6}
EXCLUSIVITY_MULTIPLIER = 2.0
REUSE_DISCOUNT_FACTOR = 0.6  # a 40 percent discount applied after exclusivity

# Per-use royalty lines (PRD §3.7): channel multiplier x tier, per-line half-up rounding.
CHANNEL_ROYALTY_MULTIPLIER = {
    "PRINT": 1.0,
    "DIGITAL": 1.25,
    "SOCIAL": 0.5,
    "SYNDICATION": 2.0,
}
TIER_THRESHOLD = 10        # ordinal ten or higher earns the high tier
TIER_MULTIPLIER_HIGH = 1.5
TIER_MULTIPLIER_LOW = 1.0

# Settlement split (PRD §3.8): photographer's share of an upheld settlement.
PHOTOGRAPHER_LIABILITY_PCT = 0.30

# Kill fee (PRD §3.4): day rate x day count x one half.
KILL_FEE_PCT = 0.5

# Roster default (PRD §3.1).
DEFAULT_RIGHTS_REVERSION_MONTHS = 24

# Logical clock default at server startup (PRD §2.4).
DEFAULT_LOGICAL_NOW = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "STAFF_DAY_RATE": 25000,
    "STAFF_PER_IMAGE_FEE": 40000,
    "FREELANCE_DAY_RATE": 20000,
    "FREELANCE_PER_IMAGE_FEE": 30000,
    "ROYALTY_RATE_PER_USE": 305,
    "WIRE_BASE_FEE": 10000,
    "STORY_BUDGET": 30000,
}
