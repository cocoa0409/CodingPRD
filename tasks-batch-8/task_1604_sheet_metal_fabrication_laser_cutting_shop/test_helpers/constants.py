"""Domain thresholds and pinned arithmetic constants from PRD §2-§3."""

# --- Logical clock (PRD §2.4) ---
CLOCK_START_ISO = "2026-08-01T00:00:00Z"

# --- Pricing pipeline (PRD §3.3) ---
BASE_CUT_OVERHEAD_SEC = 8.0
CUT_SPEED_SEC_PER_MM = 0.045
PIERCE_SEC = 1.2
TIER_RATE_STEP = 0.20
BEND_UNIT_CENTS = 150
POWDER_CENTS_PER_CM2 = 0.040
PLATING_CENTS_PER_CM2 = 0.060
ANODIZE_CENTS_PER_CM2 = 0.055
SETUP_FEE_PER_LINE = 900
MIN_BILLABLE_AREA_CM2 = 300
QTY_DISCOUNT_TIERS = ((50, 0.12), (20, 0.08), (10, 0.04))  # top-down, inclusive
EXPEDITE_MULT = {"STANDARD": 1.00, "EXPEDITE": 1.25, "RUSH": 1.50}

# --- Nesting (PRD §3.5) ---
STANDARD_SHEET_W_MM = 1200
STANDARD_SHEET_H_MM = 2400
STANDARD_SHEET_AREA_CM2 = 28800
KERF_ALLOWANCE_PER_SHEET_CM2 = 5000
MIN_REMNANT_AREA_CM2 = 2000

# --- Routing / capacity (PRD §3.6) ---
BRAKE_MIN_PER_BEND_UNIT = 3
WELD_MIN_PER_INCH = 4
POWDER_BASE_MIN = 30
POWDER_AREA_DIVISOR = 500
LASER_LOAD_MIN_PER_SHEET = 5
SLA_DAYS = {"STANDARD": 5, "EXPEDITE": 3, "RUSH": 1}
CAPACITY_HORIZON_DAYS = 12
UTILIZATION_CAP = 0.90

# --- Inspection (PRD §3.8) ---
FLATNESS_LIMIT = 0.0015

# --- Scrap credits (PRD §3.2 / §3.9) ---
CREDIT_CAP_FRACTION = 0.10
CREDIT_CAP_AREA_CM2 = 2880  # 10% of the 28,800 cm2 standard sheet
MAX_CREDIT_AREA_PER_EVENT_CM2 = 90000

# --- Quote validity (PRD §3.4) ---
QUOTE_VALIDITY_DAYS = 14

# --- Shared test default payloads ---
TEST_DEFAULTS = {
    "GRADE": {
        "alloy_family": "ALUMINUM",
        "density_g_per_cm3": 2.70,
        "hardness_factor": 1.0,
        "base_cut_rate_cents_per_sec": 2.0,
        "material_cost_cents_per_cm2": 0.058,
        "scrap_rate_cents_per_cm2": 0.020,
        "weld_compatible": True,
        "powder_compatible": True,
    },
    "CREDIT_LIMIT_CENTS": 100000000,
    "SHIFT_MINUTES_PER_DAY": 480,
}
