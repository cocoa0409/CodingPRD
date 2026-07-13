"""Domain thresholds — numeric constants from PRD calculations (PRD section 3)."""

# Method-specific pricing constants (PRD 3.2).
METHOD = {
    "SCREEN_PRINT": {
        "setup_first_color_cents": 2500,
        "setup_addl_color_cents": 1500,
        "run_addl_per_unit_cents": 40,
        "max_colors": 6,
    },
    "EMBROIDERY": {
        "setup_first_color_cents": 4000,
        "setup_addl_color_cents": 0,
        "run_addl_per_unit_cents": 0,
        "max_colors": 12,
    },
    "LASER_ENGRAVE": {
        "setup_first_color_cents": 3000,
        "setup_addl_color_cents": 0,
        "run_addl_per_unit_cents": 0,
        "max_colors": 1,
    },
}

# Order totals (PRD 3.5).
RUSH_SURCHARGE_PCT = 0.20
DEPOSIT_PCT = 0.50

# Lead-time / rush classification (PRD 3.5 / 3.6).
RUSH_THRESHOLD_DAYS = 10
ABSOLUTE_MIN_LEAD_DAYS = 3

# Spoilage tolerance (PRD 3.7).
UNDERRUN_TOL = 0.05
OVERRUN_TOL = 0.05

# Deterministic logical clock default (PRD 2.6).
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"

# Standard scenario defaults used across fixtures.
DEFAULT_IN_HANDS_ISO = "2026-05-20T00:00:00Z"
DEFAULT_INITIAL_CREDIT_CENTS = 500_000
DEFAULT_BLANK_UNIT_COST_CENTS = 150
DEFAULT_CONCURRENT_CAPACITY_UNITS = 500

# Pre-computed totals for the canonical single-line order
# (SCREEN_PRINT, quantity 200, 3 colors, tiers 48->599 and 144->499):
#   unit_price = 499; run/unit = 2*40 = 80; goods = 579*200 = 115800
#   setup = 2500 + 2*1500 = 5500; subtotal = 121300 (non-rush total)
#   deposit_required = ceil(121300 * 0.50) = 60650
CANONICAL_LINE_SUBTOTAL_CENTS = 121_300
CANONICAL_DEPOSIT_CENTS = 60_650
