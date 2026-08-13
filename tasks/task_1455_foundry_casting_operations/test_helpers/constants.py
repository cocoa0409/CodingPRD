"""Domain thresholds — numeric constants from PRD §2.7-§2.9 and §3."""

# PRD §3.2 — pattern dimension computation
SHRINK = {
    ("FERROUS", "SAND"): 0.0104,
    ("FERROUS", "INVESTMENT"): 0.0120,
    ("ALUMINUM", "SAND"): 0.0130,
    ("ALUMINUM", "INVESTMENT"): 0.0110,
}
MA_CAP_MM = {"SAND": 6.0, "INVESTMENT": 2.5}

# PRD §3.2 — qualification tolerance (deviation exactly 0.3 mm passes)
QUALIFY_TOL_MM = 0.3

# PRD §3.7 — provisional scrap recovery yield
SCRAP_PROVISIONAL_YIELD = 0.85

# PRD §2.9 — posture thresholds
CURTAIL_THRESHOLD_KG = 500

# PRD §3.4 — AUTO_CORRECT additive purity
ADDITIVE_PURITY = 1.00

# Logical-clock instants reused across scenarios (PRD §2.4)
CLOCK_MORNING = "2026-08-10T08:00:00Z"
CLOCK_POUR = "2026-08-10T10:30:00Z"
CLOCK_AFTER_COOLING = "2026-08-10T13:00:00Z"

SLOT_START = "2026-08-10T10:00:00Z"
SLOT_END = "2026-08-10T11:00:00Z"

TEST_DEFAULTS = {
    "UNIT_PRICE_CENTS": 100000,
    "MACHINING_ALLOWANCE_PCT": 0.15,
    "WARRANTY_MONTHS": 12,
    "WARRANTY_BUDGET_CENTS": 500000,
    "FURNACE_TAP_CAPACITY_KG": 5000,
    "LINE_MINUTE_CAPACITY": 480,
    "CLEANUP_BUFFER_MINUTES": 30,
    "SAND_VIRGIN_KG": 1000.0,
    "MAX_LOI_PCT": 3.0,
    "PASSING_LOI_PCT": 2.5,
    "ALLOY_GRADE": "GJS-400-15",
}

# Simple single-element chemistry spec: a 3.40 reading passes (3.2 <= 3.40 <= 3.6).
SIMPLE_SPEC = {"elements": {"C": {"min": 3.2, "max": 3.6}}}
SIMPLE_READING = {"C": 3.40}

# Full ductile-iron spec with a carbon-equivalent ceiling (PRD §3.4).
FULL_SPEC = {
    "elements": {
        "C": {"min": 3.2, "max": 3.6},
        "Si": {"min": 2.2, "max": 2.6},
        "Mn": {"min": 0.1, "max": 0.4},
        "P": {"min": 0.0, "max": 0.05},
    },
    "ce_max": 4.30,
}
FULL_READING = {"C": 3.40, "Si": 2.40, "Mn": 0.20, "P": 0.02}
