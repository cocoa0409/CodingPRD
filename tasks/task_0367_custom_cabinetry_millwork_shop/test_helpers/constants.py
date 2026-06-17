"""Domain thresholds — numeric constants from the PRD's calculations.

These mirror the basis-point tables and tier thresholds named in the PRD's
pricing, cut-list, and settlement rules. Generic NON_EXISTENT_UUID comes from
the framework.
"""

# Cut-list saw-kerf + offcut waste uplift on panel area (12%).
KERF_WASTE_BPS = 1200

# Contract-total margin multipliers (bps), indexed [margin_policy][qty_tier].
MARGIN_TABLE = {
    "STANDARD": {"SMALL": 13500, "MED": 13000, "BULK": 12500},
    "PREMIUM": {"SMALL": 16000, "MED": 15500, "BULK": 15000},
}

# Finish upcharge rates in bps of the margined line.
FINISH_BPS = {"RAW": 0, "STAIN": 800, "PAINT": 1200, "LACQUER": 2000}

# Per-line clamp (cents).
MIN_LINE_CENTS = 5000
MAX_LINE_CENTS = 5000000

# Late-fee tier rates (bps).
LATE_TIER1_BPS = 150   # 1..30 days late
LATE_TIER2_BPS = 400   # >30 days late

# Shop config defaults from the PRD.
DEFAULT_DEPOSIT_PCT_BPS = 3000
DEFAULT_RETAINAGE_PCT_BPS = 1000
DEFAULT_RUSH_SURCHARGE_BPS = 1500
DEFAULT_MAX_INSTALLS_PER_DAY = 2
DEFAULT_TAX_RATE_BPS = 0
DEFAULT_CURRENCY = "USD"

# A standard sheet area large enough that single cabinets fit in 1-2 sheets.
TEST_SHEET_AREA_MM2 = 5796000

# Convenience: cabinet dimensions used throughout the design index (panel_area = 2006400).
SPEC_W = 600
SPEC_H = 720
SPEC_D = 560
SPEC_PANEL_AREA_MM2 = 2 * (SPEC_W * SPEC_H) + 2 * (SPEC_H * SPEC_D) + 1 * (SPEC_W * SPEC_D)

TEST_DEFAULTS = {
    "BASE_UNIT_PRICE_CENTS": 100000,
    "SHEET_AREA_MM2": TEST_SHEET_AREA_MM2,
    "SHEET_PRICE_CENTS": 4000,
}
