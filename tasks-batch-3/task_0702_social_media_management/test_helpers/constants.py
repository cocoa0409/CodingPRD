"""Domain thresholds — numeric constants from PRD calculations."""

# Engagement-rate basis-point scale (PRD §3.7 / §2.6).
BPS_SCALE = 10000

# Collaboration settlement bonus tiers (PRD §3.6).
TIER2_RATE = 0.05   # cleared deliverables 3..5
TIER3_RATE = 0.10   # cleared deliverables 6..n
TIER2_FLOOR = 2     # first two cleared deliverables earn no bonus
TIER3_FLOOR = 5     # five-percent tier ends at five cleared deliverables

# Default channel publish gap (PRD §3.2).
DEFAULT_MIN_PUBLISH_GAP_MINUTES = 30

# Default schedule-slot window length (PRD §3.2).
DEFAULT_SLOT_DURATION_MINUTES = 15

# Pagination defaults (PRD §2.3).
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
