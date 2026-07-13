"""Domain thresholds — numeric constants from the PRD's arithmetic sections."""

# Loyalty tier thresholds against lifetime spend in cents (inclusive, >=). PRD §3.2.
TIER_THRESHOLDS_CENTS = {
    "SILVER": 50_000,
    "GOLD": 200_000,
    "PLATINUM": 500_000,
}

# Reload promo bonus rate by pre-reload tier. PRD §3.2.
BONUS_PCT = {"NONE": 0.0, "SILVER": 0.05, "GOLD": 0.10, "PLATINUM": 0.20}

# Gameplay points multiplier by member tier. PRD §3.3.
TIER_MULTIPLIER = {"NONE": 1.0, "SILVER": 1.1, "GOLD": 1.25, "PLATINUM": 1.5}

# Per-card purchased-balance cap in cents. PRD §3.2.
CARD_BALANCE_CAP_CENTS = 100_000

# Per-extra-guest surcharge in cents. PRD §3.7.
PER_EXTRA_GUEST_CENTS = 1_500

# Maximum aggregate venue occupancy. PRD §3.5.
MAX_VENUE_OCCUPANCY = 200

# Default logical clock at server startup. PRD §2.5.
DEFAULT_CLOCK_UTC = "2026-05-01T00:00:00Z"
