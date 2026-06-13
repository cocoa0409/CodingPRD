"""Domain thresholds and rate tables — numeric constants from the PRD pricing
and scheduling rules (§3.2-§3.8).
"""

# Per-unit material rates keyed by (material, style) — PRD §3.2.
RATE_TABLE = {
    ("CEDAR", "PRIVACY"): 42.50,
    ("CEDAR", "PICKET"): 31.00,
    ("VINYL", "PRIVACY"): 55.75,
    ("COMPOSITE", "DECK_STANDARD"): 38.25,
    ("PT_PINE", "DECK_STANDARD"): 24.80,
    ("ALUMINUM", "ORNAMENTAL"): 48.90,
}

# Flat per-line accessory adders — PRD §3.2.
ACCESSORY_ADDER = {
    "NONE": 0.00,
    "SINGLE_GATE": 285.00,
    "DOUBLE_GATE": 540.00,
    "STAIR_SET": 420.00,
}

# Labor rate per unit keyed by work_type — PRD §3.2.
LABOR_RATE = {
    "FENCE": 9.50,
    "DECK": 22.00,
}

# Pricing constants.
MOBILIZATION_FEE = 650.00
SLOPE_THRESHOLD_PCT = 15
SLOPE_MULTIPLIER = 1.12
DEFAULT_TAX_RATE_PCT = 7.25

# Draw waterfall — PRD §3.3.
DRAW_PCT = {
    "DEPOSIT": 0.20,
    "DELIVERY": 0.30,
    "FRAMING": 0.30,
    "FINAL": 0.20,
}
DEPOSIT_CAP = 10000.00

# Material take-off — PRD §3.5.
DEFAULT_WASTE_FACTOR_PCT = 10

# Dock scheduling buffer — PRD §3.5.
DOCK_BUFFER_HOURS = 4

# Warranty defaults — PRD §3.9.
DEFAULT_COVERAGE_YEARS = 5
