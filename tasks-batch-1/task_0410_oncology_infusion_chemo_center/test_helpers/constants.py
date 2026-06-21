"""Domain thresholds — numeric constants from PRD calculations and rules."""

# Calvert renal cap: GFR is capped at this value before adding 25 (PRD §3.7).
GFR_CAP = 125

# Calvert additive constant (PRD §3.7: "then adding 25").
CALVERT_ADD = 25

# BSA Mosteller denominator (PRD §2.7 / §3.1).
BSA_DENOMINATOR = 3600

# Default nurse acuity ceiling (PRD §3.3).
DEFAULT_MAX_ACUITY_LOAD = 6

# CTCAE grade threshold at/above which an event auto-holds the cycle (PRD §3.11).
TOXICITY_HOLD_GRADE = 3

# Acuity weight range (PRD §3.10).
ACUITY_MIN = 1
ACUITY_MAX = 5

THRESHOLDS = {
    "GFR_CAP": GFR_CAP,
    "CALVERT_ADD": CALVERT_ADD,
    "BSA_DENOMINATOR": BSA_DENOMINATOR,
    "DEFAULT_MAX_ACUITY_LOAD": DEFAULT_MAX_ACUITY_LOAD,
    "TOXICITY_HOLD_GRADE": TOXICITY_HOLD_GRADE,
}
