"""Domain thresholds and standard measurement inputs for the Lymphedema API.

Numeric constants are taken from the calculation rules described in the PRD.
"""

# Garment classification thresholds (ml) by region group (PRD §3.6)
THRESHOLDS = {
    "ARM_BUMP_THRESHOLD_ML": 150,
    "LEG_BUMP_THRESHOLD_ML": 500,
    "OTHER_BUMP_THRESHOLD_ML": 150,
    "ARM_CUSTOM_THRESHOLD_ML": 400,
    "LEG_CUSTOM_THRESHOLD_ML": 1200,
    "OTHER_CUSTOM_THRESHOLD_ML": 400,
    "MAX_CLASS": 4,
    # Outcome / phase thresholds (PRD §3.8)
    "MAINTENANCE_THRESHOLD": 50,
    "EXCELLENT_MIN": 50,
    "GOOD_MIN": 25,
    "PARTIAL_MIN": 0,
    # Scheduling buffer (PRD §3.5)
    "THERAPIST_BUFFER_MINUTES": 15,
    "PI": 3.141592653589793,
}

# A well-formed affected/contralateral measurement pair reused across setups.
# For a LEFT_ARM STAGE_II evaluation with interval_cm 4 this yields
# limb_volume_ml 527.1, contralateral_volume_ml 374.7, excess_volume_ml 152.4.
STANDARD_CIRCUMFERENCES = [18, 18, 20, 22, 24]
STANDARD_CONTRALATERAL = [16, 16, 17, 18, 19]
STANDARD_INTERVAL_CM = 4

# The "current" (improved) measurement used for reassessment scenarios:
# limb_volume_ml 419.5, excess_volume_ml 44.8.
IMPROVED_CIRCUMFERENCES = [17, 17, 18, 19, 20]

# Default auth effective window comfortably containing the standard session dates.
DEFAULT_WINDOW_START = "2026-05-01"
DEFAULT_WINDOW_END = "2026-12-31"

# Standard L-code fulfilled by an off-the-shelf SLEEVE (LEFT_ARM garment order).
STANDARD_LCODE = "L8100"
