"""Domain thresholds — numeric constants from the PRD calculations (§3, §2.6)."""

# Subsidy: only ENTREE and HEALTHY items are subsidizable (§3.3).
SUBSIDIZED_CATEGORIES = ["ENTREE", "HEALTHY"]

# Catering estimate overhead factor (§3.6).
EVENT_OVERHEAD_FACTOR = 1.20

# Catering client-charge service fee (§3.6).
SERVICE_FEE_PCT = 0.18

# Catering volume discount tiers by headcount (§3.6).
VOLUME_DISCOUNT_TIERS = [
    (100, 0.15),
    (50, 0.10),
    (20, 0.05),
]

# Vendor-invoice three-way match tolerance (§3.7).
MATCH_TOLERANCE_CENTS = 500

# Default session changeover buffer when a site omits it (§3.1).
DEFAULT_CHANGEOVER_BUFFER_MINUTES = 30

# Allergen enum values (§3.1).
ALLERGENS = ["PEANUTS", "TREE_NUTS", "DAIRY", "GLUTEN", "SOY", "SHELLFISH", "EGGS"]

# Logical clock default at server startup (§2.4).
CLOCK_DEFAULT_UTC = "2026-03-01T00:00:00Z"
