"""Domain thresholds — numeric constants from the PRD's award formulas.

All amounts are integer cents (PRD §2.6). NON_EXISTENT_UUID comes from the
framework barrel export.
"""

# Per-component award caps (PRD §3.3): each component capped at $41,500.
REPAIR_CATEGORY_CAP_CENTS = 4_150_000
PERSONAL_CATEGORY_CAP_CENTS = 4_150_000
REPLACEMENT_CAP_CENTS = 4_150_000

# SBA referral eligibility thresholds (PRD §3.7).
SBA_INCOME_CEILING_CENTS = 7_500_000   # $75,000 ceiling, at-or-below qualifies
SBA_LOSS_THRESHOLD_CENTS = 3_000_000   # $30,000 threshold, strictly-greater qualifies

# Default per-household IHP cap used across most test declarations.
DEFAULT_IHP_MAX_GRANT_CENTS = 4_250_000

# Inspector default travel buffer (PRD §3.1).
DEFAULT_TRAVEL_BUFFER_MINUTES = 30

# Fixed cap-and-offset waterfall category order (PRD §3.6).
CATEGORY_ORDER = [
    "RENTAL_ASSISTANCE",
    "REPAIR_ASSISTANCE",
    "PERSONAL_PROPERTY",
    "REPLACEMENT",
]

# A non-existent UUID for not-found tests (matches the corner-design literals).
ZERO_UUID = "00000000-0000-0000-0000-000000000000"
