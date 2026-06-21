"""Domain thresholds — numeric constants from the PRD calculations (§3)."""

# Waiver-cap tiers (PRD §3.6): tier keyed on the pre-waiver balance.
WAIVER_TIER1_CENTS = 50000   # balance < TIER1 -> cap 100%
WAIVER_TIER2_CENTS = 150000  # TIER1 <= balance < TIER2 -> cap 50%; >= TIER2 -> cap 25%

# Provider standing (PRD §3.7): suspension penalty in percentage points.
SUSPENSION_PENALTY_PCT = 20.0

# Default lot configuration used across difficulty/corner recipes.
DEFAULT_LOT = {
    "daily_storage_rate_cents": 5000,
    "admin_fee_cents": 7500,
    "lien_processing_fee_cents": 3000,
    "statutory_hold_days": 30,
    "notice_grace_days": 10,
}

# Default provider offer time-to-accept (PRD §3.2).
DEFAULT_OFFER_TTL_MINUTES = 30
