"""Domain thresholds and numeric constants from the PRD's calculation rules."""

# Logical clock startup default (PRD §2.4).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Cylinder size specs: water capacity in liters (PRD §3.2).
SIZE_SPECS = {"SMALL": 10, "STANDARD": 50, "LARGE": 100}

# Loss fees keyed by size, in cents (PRD §3.5).
SIZE_LOSS_FEE_CENTS = {"SMALL": 15000, "STANDARD": 45000, "LARGE": 80000}

# Hydrostatic retest intervals in months, keyed by service gas (PRD §3.2).
HYDRO_INTERVAL_MONTHS = {"O2": 12, "N2": 12, "AR": 12, "CO2": 6, "H2": 12, "HE": 12}
DUE_SOON_DAYS = 30

# Fill-draw rule constants (PRD §3.3).
CONVERSION_DIVISOR = 100
LINE_LOSS_LITERS = 2
STANDARD_RESIDUAL_BAR = 5
MIN_TANK_RESERVE_LITERS = 100

# Purity grade limits in ppm, keyed by product then analyte (PRD §3.4).
GRADE_LIMITS_PPM = {
    "O2": {"CO": 10, "H2O": 20},
    "N2": {"O2": 10, "H2O": 10},
    "AR": {"O2": 10, "H2O": 10},
    "CO2": {"H2O": 10, "THC": 20},
    "H2": {"O2": 5, "H2O": 10},
    "HE": {"O2": 5, "H2O": 5},
}
MARGINAL_FACTOR = 1.5

# Demurrage tier boundaries and multipliers (PRD §3.6).
TIER1_LAST_DAY = 7
TIER2_LAST_DAY = 30
TIER1_MULT = 1.0
TIER2_MULT = 1.5
TIER3_MULT = 2.0

# Blend service-fee tiers keyed on component cost (PRD §3.9).
FEE_FLAT_CENTS = 15000
FEE_TIER1_LIMIT = 100000
FEE_TIER2_LIMIT = 500000
FEE_TIER2_RATE = 0.12
FEE_TIER3_RATE = 0.10

# Replenishment constants (PRD §3.8).
TRUCK_CAPACITY_LITERS = 20000
MIN_REPLENISHMENT_GAP_HOURS = 24

# Credit-hold hysteresis (PRD §3.5).
HOLD_RELEASE_RATIO = 0.8

# Common test defaults.
TEST_DEFAULTS = {
    "TANK_CAPACITY_LITERS": 10000,
    "TANK_INITIAL_LEVEL_LITERS": 5000,
    "TANK_REORDER_POINT_LITERS": 500,
    "TARGET_FILL_PRESSURE_BAR": 200,
    "DAILY_RATE_CENTS": 1000,
    "CREDIT_LIMIT_CENTS": 100000,
    "LAST_HYDRO_DATE": "2025-09-01",
}
