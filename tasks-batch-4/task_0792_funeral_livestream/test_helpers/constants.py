"""Domain thresholds — numeric constants from the PRD's billing, donation,
and access-lockout rules (PRD §2.10, §3.6, §3.9)."""

# Service billing (PRD §3.6)
BASE_FEE_CENTS = 15000
PER_CAMERA_CENTS = 5000
INCLUDED_MINUTES = 120
OVERAGE_TIER1_MINUTES = 60          # first 60 overage minutes at tier1 rate
OVERAGE_TIER1_RATE_CENTS = 100      # per minute
OVERAGE_TIER2_RATE_CENTS = 150      # per minute beyond the first 60 overage minutes
PRIORITY_SUPPORT_SURCHARGE_CENTS = 10000

# Donation ledger (PRD §3.9 / §2.10)
FEE_PCT = 0.029
FEE_FLAT_CENTS = 30

# Guest-link access lockout (PRD §3.9)
MAX_FAILED_ACCESS_ATTEMPTS = 5

# Camera-count constraint (PRD §3.3)
MIN_CAMERA_COUNT = 1
MAX_CAMERA_COUNT = 4

# Default logical clock before any set call (PRD §2.11)
DEFAULT_CLOCK_UTC = "2026-03-01T00:00:00Z"
