"""Domain thresholds — numeric constants named in PRD sections 2 and 3."""

# PRD 3.2: production forecast inputs.
LOOKBACK_DAYS = 28
GROWTH_FACTOR = 1.05
DEFAULT_SEED_SERVINGS = 60

# PRD 3.3: rescue-cap ratio bounding a single item's draw from a RESCUE batch.
RESCUE_CAP_RATIO = 0.5

# PRD 3.4: volunteer hours ledger constants.
PENALTY_HOURS = 2.0
MAX_STRIKES = 3
CANCEL_LOCKOUT_HOURS = 24

# PRD 3.8: per-serving handling fee charged for RESCUE-fed lines.
HANDLING_FEE_CENTS = 35

# PRD 3.8: waste ratio alert threshold (strictly greater than).
WASTE_ALERT_THRESHOLD = 0.15

# Default startup instant of the logical clock (PRD 2.5).
CLOCK_START = "2026-08-01T00:00:00Z"
