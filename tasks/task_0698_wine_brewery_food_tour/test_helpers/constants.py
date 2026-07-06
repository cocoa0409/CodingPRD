"""Domain thresholds — numeric constants from PRD calculations (§3.7) and
global rules (§2.3, §2.5)."""

# Group-size pricing tiers (PRD §3.7 "The price quote").
PRICING_TIERS = {
    "TIER_12_PCT": 0.15,   # party_size >= 12
    "TIER_8_PCT": 0.10,    # party_size >= 8
    "TIER_4_PCT": 0.05,    # party_size >= 4
    "TIER_0_PCT": 0.00,    # party_size < 4
}

# Gratuity ceiling (PRD §3.1 / §3.7).
MAX_GRATUITY_PCT = 0.30
DEFAULT_GRATUITY_PCT = 0.18

# Commission ceiling (PRD §3.2).
MAX_COMMISSION_PCT = 0.50

# Cancellation-refund lead-time tiers, in hours (PRD §3.7 "Cancellation refund").
FULL_REFUND_HOURS = 168   # >= 7 days -> 100%
HALF_REFUND_HOURS = 48    # >= 48h and < 168h -> 50%; < 48h -> 0%

# Default minimum guest age (PRD §3.1).
DEFAULT_MIN_GUEST_AGE = 21

# Venue-confirmation revision limit (PRD §3.4).
REVISION_LIMIT = 3

# Logical-clock startup default (PRD §2.5).
CLOCK_STARTUP_DEFAULT = "2026-03-01T00:00:00Z"

# Pagination bounds (PRD §2.3).
PAGINATION = {"DEFAULT_LIMIT": 10, "MIN_LIMIT": 1, "MAX_LIMIT": 100, "MIN_OFFSET": 0}
