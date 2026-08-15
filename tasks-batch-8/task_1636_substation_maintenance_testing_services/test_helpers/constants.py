"""Domain thresholds — numeric constants stated in the PRD."""

# Logical clock startup default (PRD §2.7)
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# Condition score component values and defect penalties (PRD §3.5)
SCORE_PASS = 100
SCORE_MARGINAL = 70
SCORE_FAIL = 30
PENALTY_C1 = 5
PENALTY_C2 = 2
PENALTY_C3 = 1
TRAILING_MONTHS = 24

# Defect SLA days by severity (PRD §3.6)
SLA_DAYS = {"C1": 30, "C2": 90, "C3": 365}

# Defect deferral hard cap (PRD §3.6)
DEFERRAL_CAP = 2

# Work-order cost rollup tiering (PRD §3.6 / §2.5)
MOBILIZATION_TIER_THRESHOLD = 500.00
MOBILIZATION_FEE_RATE_HIGH_TIER = 0.04
MOBILIZATION_FEE_RATE_LOW_TIER = 0.05

# Spare selector scoring weights (PRD §3.7)
SELECTOR_ADEQUACY_WEIGHT = 100
SELECTOR_IMPEDANCE_WEIGHT = 25
SELECTOR_IMPEDANCE_TOLERANCE_PCT = 4.0
SELECTOR_LOCATION_BONUS = 10
MOBILE_MVA_DERATE = 0.9

# Relay coordination margin multiplier (PRD §3.8)
COORDINATION_MARGIN = 1.3

# Insulation-resistance temperature correction reference (PRD §3.4)
IR_REFERENCE_TEMP_C = 40
IR_HALVING_STEP_C = 10

# Outage-window minimum gap to the nearest non-terminal window (PRD §3.2)
OUTAGE_BUFFER_HOURS = 24

# Pagination defaults (PRD §2.3)
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
