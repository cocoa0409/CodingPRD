"""Domain thresholds — numeric constants from PRD calculation prose (§2.4–§3.9)."""

# Logical clock startup value (PRD §2.4).
CLOCK_T0 = "2026-08-01T00:00:00Z"

# Variety yield factors for the provisional batch yield (PRD §3.2).
VARIETY_YIELD_FACTOR = {"WHITE_CORN": 1.70, "YELLOW_CORN": 1.65, "BLUE_CORN": 1.60}

# Mill moisture target; only moisture above this is penalized (PRD §3.2).
TARGET_MASA_MOISTURE_PCT = 55

# Masa loss factor applied when computing a run's masa_required_kg (PRD §3.5).
MASA_LOSS_FACTOR = 1.05

# Shelf life per preservative system (PRD §3.4).
SHELF_LIFE_DAYS = {"NONE": 5, "PROPIONATE": 20, "FUMARIC_ACID": 45}

# Allergen ranks driving the changeover level matrix (PRD §3.6).
ALLERGEN_RANK = {"CORN_ONLY": 0, "WHEAT_FLOUR": 1, "SOY_BLENDED": 2}

# Changeover downtime bases and the diameter penalty (PRD §3.6).
CHANGEOVER_BASE_MIN = {"FLUSH": 30, "WET_WASH": 60, "FULL_SANITATION": 120}
DIAMETER_PENALTY_MIN = 15

# Seasonal waterfall tier factors and the strict-window threshold (PRD §3.8).
TIER_FACTOR = {"A": 1.0, "B": 0.8, "C": 0.6}
SPIKE_MULTIPLIER_THRESHOLD = 1.5

# Weight-check minimum sample cardinality (PRD §3.7).
SAMPLE_MIN = 3

# Run completion attainment ratio (PRD §3.5).
RUN_COMPLETION_RATIO = 0.95

# Default weight tolerance applied when the field is omitted (PRD §3.4).
DEFAULT_WEIGHT_TOLERANCE_PCT = 2.0

THRESHOLDS = {
    "TARGET_MASA_MOISTURE_PCT": TARGET_MASA_MOISTURE_PCT,
    "SAMPLE_MIN": SAMPLE_MIN,
    "SPIKE_MULTIPLIER_THRESHOLD": SPIKE_MULTIPLIER_THRESHOLD,
    "DIAMETER_PENALTY_MIN": DIAMETER_PENALTY_MIN,
    "RUN_COMPLETION_RATIO": RUN_COMPLETION_RATIO,
}

TEST_DEFAULTS = {
    "LOT_RECEIVED_KG": 5000,
    "BATCH_CORN_KG": 1000,
    "COOK_MINUTES": 90,
    "STEEP_TARGET_HOURS": 8,
    # Standard mill inputs -> actual_masa_kg 1552.0 for a 1000 kg WHITE_CORN batch.
    "MILLED_MASA_KG": 1620,
    "MEASURED_MOISTURE_PCT": 58,
    "MASA_WASTED_KG": 20,
    "STANDARD_ACTUAL_MASA_KG": 1552.0,
    "STANDARD_THEORETICAL_MASA_KG": 1700.0,
    "STANDARD_YIELD_VARIANCE_PCT": -8.71,
    "LINE_CASES_PER_HOUR": 100,
    "VEHICLE_CAPACITY_CASES": 100,
}
