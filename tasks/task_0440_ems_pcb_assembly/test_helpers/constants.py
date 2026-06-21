"""Domain thresholds — numeric constants from the PRD calculations (§3)."""

# First-pass-yield floor for the finalize-test branch (PRD §3.8).
MIN_YIELD_PCT = 70

# Rework handling-surcharge tier constants (PRD §3.9).
HANDLING_FLAT_CENTS = 1500
MID_RATE = 0.20
HIGH_RATE = 0.30
LOW_TIER_MAX = 5000     # base part cost <= 5000 -> flat surcharge
MID_TIER_MAX = 20000    # 5001..20000 inclusive -> MID_RATE; > 20000 -> HIGH_RATE

# RMA warranty-credit factors by failure class (PRD §3.10).
WORKMANSHIP_FACTOR = 1.00
COMPONENT_FACTOR = 0.60
DESIGN_FACTOR = 0.80
NO_FAULT_FACTOR = 0.00
REWORK_PENALTY = 0.10

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
MIN_LIMIT = 1
