"""Numeric thresholds and pinned coefficients drawn from the PRD.

Anything a test compares against belongs here so the comparison reads as a
contract reference rather than as a magic number.
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# Logical clock (PRD 2.6)
# --------------------------------------------------------------------------- #

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_RESPONSE = "2026-08-01T00:00:00.000Z"


# --------------------------------------------------------------------------- #
# Pagination (PRD 2.3)
# --------------------------------------------------------------------------- #

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


# --------------------------------------------------------------------------- #
# Plant defaults and posture thresholds (PRD 3.1, 2.9)
# --------------------------------------------------------------------------- #

DEFAULT_NATURAL_PURITY_FLOOR_PCT = 88.0
DEFAULT_SYNTHETIC_MOISTURE_CEILING_PCT = 12.0

POSTURE_FROZEN_HELD_RUN_COUNT = 3
POSTURE_RESTRICTED_HELD_RUN_COUNT = 1
POSTURE_RESTRICTED_STUCCO_TONS = 40.0


# --------------------------------------------------------------------------- #
# Assay disposition (PRD 3.2)
# --------------------------------------------------------------------------- #

CHLORIDE_CEILING_PPM = 250
MAX_ASSAYS = 3
ASSAY_VALIDITY_DAYS = 30


# --------------------------------------------------------------------------- #
# Calcination yield (PRD 3.3)
# --------------------------------------------------------------------------- #

HEMIHYDRATE_FACTOR = 0.8437
INERT_CARRYOVER_FACTOR = 1.0


# --------------------------------------------------------------------------- #
# Stucco grading bands (PRD 3.4)
# --------------------------------------------------------------------------- #

COMBINED_WATER_FAIL_LOW_PCT = 4.20
COMBINED_WATER_FAIL_HIGH_PCT = 6.50
FREE_WATER_FAIL_PCT = 0.50
FREE_WATER_MARGINAL_PCT = 0.30
SET_TIME_FAIL_LOW_MIN = 3.00
SET_TIME_FAIL_HIGH_MIN = 15.00
SET_TIME_MARGINAL_LOW_MIN = 4.00
SET_TIME_MARGINAL_HIGH_MIN = 12.00


# --------------------------------------------------------------------------- #
# Draft-time process envelope (PRD 3.5)
# --------------------------------------------------------------------------- #

PAPER_TENSION_PIVOT_FPM = 250
PAPER_TENSION_SLOPE_LB_PER_FPM = 0.06

KILN_EFFICIENCY_LOW_DWELL_MINUTES = 32
KILN_EFFICIENCY_HIGH_DWELL_MINUTES = 45
KILN_EFFICIENCY_LOW = 0.72
KILN_EFFICIENCY_MID = 0.81
KILN_EFFICIENCY_HIGH = 0.86
KILN_DRYING_CAPACITY_COEFFICIENT = 38.0
EXIT_MOISTURE_TOLERANCE_PCT = 0.10

LINE_SPEED_MIN_FPM = 100
LINE_SPEED_MAX_FPM = 1200
KILN_DWELL_MIN_MINUTES = 10
KILN_DWELL_MAX_MINUTES = 120
EXIT_MOISTURE_TARGET_MIN_PCT = 0.05
EXIT_MOISTURE_TARGET_MAX_PCT = 2.00


# --------------------------------------------------------------------------- #
# Changeover matrix and capacity (PRD 3.5)
# --------------------------------------------------------------------------- #

CHANGEOVER_COLD_START_MINUTES = 45
CHANGEOVER_SAME_SPEC_MINUTES = 0
CHANGEOVER_SAME_THICKNESS_AND_FAMILY_MINUTES = 20
CHANGEOVER_SAME_THICKNESS_ONLY_MINUTES = 55
CHANGEOVER_SAME_FAMILY_ONLY_MINUTES = 75
CHANGEOVER_NEITHER_MINUTES = 110
CHANGEOVER_FIRE_RATED_PURGE_MINUTES = 25

MSF_PER_FOOT_DIVISOR = 12
MSF_PER_THOUSAND = 1000


# --------------------------------------------------------------------------- #
# Kiln energy model (PRD 3.5)
# --------------------------------------------------------------------------- #

KILN_LATENT_BTU_PER_LB = 1150
KILN_SPEED_PIVOT_FPM = 350
KILN_SPEED_SLOPE = 0.0004
KILN_THICKNESS_REFERENCE_IN = 0.5
KILN_THICKNESS_SLOPE = 0.6
KILN_THICKNESS_MULTIPLIER_CAP = 1.35
KILN_HOLD_PER_DWELL_MINUTE = 0.004

BOARD_TYPE_ENERGY_ADDER_PER_MSF: dict[str, float] = {
    "REGULAR": 0.0,
    "TYPE_X": 0.018,
    "TYPE_C": 0.026,
    "MOLD_RESISTANT": 0.010,
    "ABUSE_RESISTANT": 0.014,
}


# --------------------------------------------------------------------------- #
# Run completion auto-hold gates (PRD 3.6)
# --------------------------------------------------------------------------- #

EDGE_DEFECT_HOLD_PPM = 1500
END_DEFECT_HOLD_PPM = 900


# --------------------------------------------------------------------------- #
# Quality evaluation (PRD 3.7)
# --------------------------------------------------------------------------- #

MIN_SPECIMENS_FOR_EVALUATION = 3
DOWNGRADE_FAIL_RATE_CEILING = 0.2500


# --------------------------------------------------------------------------- #
# Load orders and freight (PRD 3.8, 3.1)
# --------------------------------------------------------------------------- #

TRAILER_WEIGHT_CEILING_LB = 48000
OVERWEIGHT_THRESHOLD_LB = 44000
OVERWEIGHT_FEE_PER_LB = 0.02
POUNDS_PER_TON = 2000

MIN_BOARDS_PER_BUNDLE = 2
MAX_BOARDS_PER_BUNDLE_CEILING = 80

RATE_ZONE_BOUNDARIES_MILES = (150, 350, 600)
BASE_RATE_BY_ZONE: dict[str, float] = {
    "ZONE_1": 8.50,
    "ZONE_2": 12.75,
    "ZONE_3": 17.40,
    "ZONE_4": 23.10,
}


# --------------------------------------------------------------------------- #
# Maintenance outages (PRD 3.9)
# --------------------------------------------------------------------------- #

MAX_DEFERRALS = 2
SEASONALITY_APPROVAL_CEILING = 0.90
DEFERRAL_OVERRIDE_COUNT = 2

SEASONALITY_INDEX_BY_MONTH: dict[int, float] = {
    1: 0.62,
    2: 0.66,
    3: 0.85,
    4: 1.05,
    5: 1.18,
    6: 1.24,
    7: 1.20,
    8: 1.16,
    9: 1.06,
    10: 0.90,
    11: 0.80,
    12: 0.68,
}

SECONDS_PER_HOUR = 3600

OUTAGE_CANCEL_REASON_PREFIX = "OUTAGE_APPROVED:"
RUN_SCRAPPED_CANCEL_REASON = "RUN_SCRAPPED"


# --------------------------------------------------------------------------- #
# Rounding tolerances used by assertions
# --------------------------------------------------------------------------- #

TOL_2DP = 0.005
TOL_3DP = 0.0005
TOL_4DP = 0.00005
TOL_6DP = 0.0000005
