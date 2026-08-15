"""Domain thresholds and shared values from PRD calculation narratives."""

# Throughput preview (PRD section 3.3)
BASE_CYCLE_S = 10.0
WEIGHT_COEFF_S_PER_G = 0.08
LABELER_CAP_CPH = 240
YIELD_FRACTION = 0.97

# Resin reconciliation (PRD section 3.6)
VARIANCE_TOLERANCE_PCT = 3.0

# AQL band table (PRD section 3.7), keyed on lot_size inclusive bounds
AQL_BANDS = [
    (280, 20, 1, 1),
    (1200, 50, 2, 2),
    (10000, 125, 3, 4),
    (None, 200, 5, 6),  # 10001 and up
]

# Freight-of-air pricing (PRD section 3.8)
DIM_DIVISOR_CM3_PER_KG = 6000
PALLET_CUBE_CM3 = 144000
PALLET_TARE_KG = 20
BOTTLES_PER_PALLET = 1500
PREFORMS_PER_PALLET = 30000
TRUCK_CUBE_CM3 = 96000000
TRUCK_PAYLOAD_KG = 24000
ONSITE_FEE_CENTS_PER_BOTTLE = 40

# Scheduling changeover buffer (PRD section 3.5), minutes
MOLD_CHANGE_BUFFER_MIN_DIFFERENT = 90
MOLD_CHANGE_BUFFER_MIN_SAME = 0

# Material release uplift factor (PRD section 3.5)
RELEASE_MATERIAL_UPLIFT = 1.05

# Standard logical-clock values used across scenarios (PRD section 2.4:
# the clock starts at exactly 2026-08-01T00:00:00Z)
CLOCK_DEFAULT_START = "2026-08-01T00:00:00Z"
SLOT_START = "2026-08-02T10:00:00Z"
SLOT_END = "2026-08-02T14:00:00Z"
RUN_CLOCK = "2026-08-02T11:00:00Z"
DOCK_WINDOW_START = "2026-08-03T10:00:00Z"
DOCK_WINDOW_END = "2026-08-03T12:00:00Z"
DOCK_LOAD_CLOCK = "2026-08-03T11:00:00Z"

# Standard marginal tier card used by freight scenarios
MAIN_TIERS = [
    {"min_kg": 0, "rate_cents_per_kg": 120},
    {"min_kg": 500, "rate_cents_per_kg": 90},
    {"min_kg": 2000, "rate_cents_per_kg": 60},
]
FLAT_TIERS = [{"min_kg": 0, "rate_cents_per_kg": 120}]

# Purge matrix (PRD section 3.6): from-class -> to-class -> multiplier
PURGE_MATRIX = {
    "CLEAR": {"CLEAR": 0.0, "LIGHT": 1.0, "DARK": 1.0},
    "LIGHT": {"CLEAR": 2.0, "LIGHT": 0.0, "DARK": 1.0},
    "DARK": {"CLEAR": 3.0, "LIGHT": 2.5, "DARK": 0.0},
}
