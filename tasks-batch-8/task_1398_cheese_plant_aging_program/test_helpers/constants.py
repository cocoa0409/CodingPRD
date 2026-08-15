"""Domain thresholds — numeric constants stated in the PRD.

The logical clock reads exactly DEFAULT_CLOCK before any clock call is made.
"""

DEFAULT_CLOCK = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Milk safety acceptance gates
    "SCC_MAX": 400000,
    # Aging room environment band (inclusive boundaries)
    "TEMP_MIN_C": 7.0,
    "TEMP_MAX_C": 13.0,
    "HUMIDITY_MIN_PCT": 80.0,
    "HUMIDITY_MAX_PCT": 90.0,
    # Cut-wrap waste tolerance fraction of exact input weight
    "WASTE_TOLERANCE_PCT": 0.02,
    # Grading score ladder boundary
    "CONDEMN_SCORE_MAX": 2,
    "GRADE_A_SCORE_MIN": 8,
}

MAKE_STEPS_REQUIRED = {"CHEDDAR": 8, "COLBY": 6, "BRICK": 5, "MUENSTER": 5}

MIN_AGE_DAYS = {"CHEDDAR": 60, "COLBY": 0, "BRICK": 30, "MUENSTER": 21}

WHEEL_WEIGHT_KG = {"CHEDDAR": 18.0, "COLBY": 12.0, "BRICK": 2.5, "MUENSTER": 3.0}

TURN_INTERVAL_DAYS = {"CHEDDAR": 7, "COLBY": 5, "BRICK": 3, "MUENSTER": 3}

# Provisional-yield component model constants
FAT_RECOVERY = {"CHEDDAR": 0.93, "COLBY": 0.92, "BRICK": 0.91, "MUENSTER": 0.90}
PROTEIN_RECOVERY = {"CHEDDAR": 0.78, "COLBY": 0.77, "BRICK": 0.76, "MUENSTER": 0.75}
OTHER_SOLIDS_FACTOR = 5.7
TARGET_MOISTURE = {"CHEDDAR": 0.39, "COLBY": 0.40, "BRICK": 0.42, "MUENSTER": 0.44}

# Grading bands
VARIETY_MOISTURE_MAX = {"CHEDDAR": 39.0, "COLBY": 40.0, "BRICK": 44.0, "MUENSTER": 46.0}
VARIETY_MOISTURE_GRADE_A_MAX = {"CHEDDAR": 37.0, "COLBY": 38.0, "BRICK": 42.0, "MUENSTER": 44.0}
VARIETY_FDB_MIN = {"CHEDDAR": 50.0, "COLBY": 50.0, "BRICK": 50.0, "MUENSTER": 48.0}
