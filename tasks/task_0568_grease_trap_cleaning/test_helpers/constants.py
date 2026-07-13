"""Domain thresholds — numeric constants drawn from the PRD calculations (§2, §3)."""

# Logical clock (PRD §2.5): server startup default.
DEFAULT_CLOCK = "2026-05-01T00:00:00Z"

# Work-order billable value (PRD §3.3).
GREASE_TRAP_FEE_CENTS = 12500
HOOD_FEE_CENTS = 17500
EMERGENCY_SURCHARGE_CENTS = 8000

# Pump-out disposal fee tiers (PRD §3.4).
TIER1_MAX_GAL = 500
TIER2_MAX_GAL = 1500
RATE1_CENTS_PER_GAL = 40
RATE2_CENTS_PER_GAL = 35
RATE3_CENTS_PER_GAL = 30
FOG_SURCHARGE_PCT = 0.20
HAZMAT_FLAT_CENTS = 5000

# FOG 25% rule boundary (PRD §3.4).
FOG_RULE_THRESHOLD = 25.0

# Compliance grading horizons in days (PRD §3.2).
AS_OF_HORIZON_DAYS = 7
PROJECTED_HORIZON_DAYS = 30
DUE_SOON_HORIZON_DAYS = 7

# Customer defaults (PRD §3.1).
DEFAULT_CREDIT_LIMIT_CENTS = 500000

# Equipment service buffer (PRD §3.3).
EQUIPMENT_SERVICE_BUFFER_HOURS = 24

# Pagination (PRD §2.3).
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_LIMIT_DEFAULT = 10
