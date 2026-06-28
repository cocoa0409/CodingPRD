"""Domain thresholds — numeric constants from the Bridal Beauty PRD calculations."""

# Pricing (§3.4)
BRIDE_SURCHARGE_MULT = 1.5

# Deposit split tiers (§3.7) — half-open bands keyed on contracted_total_cents
TIER1_CEIL_CENTS = 50000      # below -> LOW band
TIER2_CEIL_CENTS = 200000     # [50000, 200000) -> MID band; >= 200000 -> HIGH band
DEP_PCT_LOW = 0.25
DEP_PCT_MID = 0.30
DEP_PCT_HIGH = 0.40

# Add-on pricing (§3.13)
TOUCH_UP_FACTOR = 0.5
EXTENDED_STAY_BLOCK_CENTS = 8000
EXTENDED_STAY_BLOCK_MINUTES = 30

# Cancellation refund tiers (§3.16) — hours remaining, lower bound inclusive
FULL_REFUND_MIN_HOURS = 720    # >= 720h -> FULL_REFUND
DEPOSIT_FORFEIT_MIN_HOURS = 72  # >= 72h and < 720h -> DEPOSIT_FORFEIT; < 72h -> FULL_FORFEIT

# Travel buffer between assignment windows (§3.11)
TRAVEL_BUFFER_MINUTES = 60

# Server logical clock default (§2.6)
CLOCK_DEFAULT_UTC = "2026-01-01T00:00:00Z"
