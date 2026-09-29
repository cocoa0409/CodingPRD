"""Domain thresholds and canonical test data drawn from the PRD's calculations."""

# --- The logical project clock (PRD §2.5) --------------------------------
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
CLOCK_T0 = "2026-08-03T08:00:00Z"
CLOCK_HANG_DAY = "2026-08-10T09:00:00Z"
CLOCK_HANG_DAY_EVENING = "2026-08-10T19:00:00Z"
CLOCK_ZONE_B_HANG = "2026-08-11T09:00:00Z"
CLOCK_FIELD_TEST_DAY = "2026-08-13T09:00:00Z"
CLOCK_RECERTIFY_DAY = "2026-08-14T09:00:00Z"

# --- The unitized-versus-stick-built fork (PRD §3.1) --------------------
SHOP_HOURS_PER_SQM = {"UNITIZED": 0.55, "STICK_BUILT": 0.18}
FIELD_CREW_SIZE = {"UNITIZED": 4, "STICK_BUILT": 8}

# --- Thermal movement allowance (PRD §3.1) ------------------------------
THERMAL_COEFFICIENT_PER_C = 0.0000234
SYSTEM_FACTOR = {"UNITIZED": 1.00, "STICK_BUILT": 1.25}
ANCHOR_FACTOR = {"SLOTTED": 1.30, "PINNED": 1.15, "FIXED": 1.00}
ELEVATION_ADDEND_LOW_MM = 0.00       # height_m <= 20.0
ELEVATION_ADDEND_MID_MM = 1.50       # 20.0 < height_m <= 40.0
ELEVATION_ADDEND_HIGH_MM = 3.00      # height_m > 40.0
ELEVATION_BAND_LOW_M = 20.0
ELEVATION_BAND_MID_M = 40.0

# --- Allowable mullion deflection (PRD §3.1) ----------------------------
DEFLECTION_DIVISOR = {"UNITIZED": 240, "STICK_BUILT": 175}

# --- Mockup chamber invoice (PRD §3.3) ---------------------------------
MOCKUP_BASE_FEE_CENTS = 480_000
MOCKUP_CHAMBER_HOUR_RATE_CENTS = 21_500
MOCKUP_SURCHARGE_TIERS = [
    (600_000, 0.02),
    (800_000, 0.04),
    (2_000_000, 0.06),
]
MOCKUP_SURCHARGE_TOP_RATE = 0.10

# --- Mockup pass lines (PRD §3.3) --------------------------------------
MOCKUP_AIR_LIMIT_CFM = 0.06
MOCKUP_DEFLECTION_LIMIT_MM = 19.00

# --- Procurement risk (PRD §3.4) ---------------------------------------
RISK_HORIZON_DAYS = {"NOMINAL": 90, "EXPEDITE_ADJUSTED": 45}
RISK_REFIRE_PENALTY_DAYS = 21
RISK_EXPEDITE_CREDIT_DAYS = 10
RISK_MAX_TOLERATED_COATING_REVISIONS = 2
RISK_WEIGHT_LEAD = 0.45
RISK_WEIGHT_CALENDAR = 0.35
RISK_WEIGHT_COATING = 0.20
RISK_RELEASE_THRESHOLD = 70.00

# --- Glass lite ledger (PRD §2.10, §3.4) -------------------------------
BREAKAGE_STOCK_RATE = 0.03           # of received_lites, floored
STANDARD_LITES_PER_PANEL = 2

# --- Field labor (PRD §3.7) --------------------------------------------
PANELS_PER_CREW_DAY = {"UNITIZED": 12, "STICK_BUILT": 6}
STANDARD_SHIFT_HOURS = 8.0
MAX_SHIFT_HOURS = 16.0
OVERTIME_MULTIPLIER = 1.5
ELEVATION_FACTOR_ABOVE_20 = 1.15
ELEVATION_FACTOR_AT_OR_BELOW_20 = 1.00
ELEVATION_FACTOR_THRESHOLD_M = 20.0

# --- Field test pass lines (PRD §3.8) ----------------------------------
FIELD_AIR_LIMIT_CFM = 0.06

# --- Embed survey / hoisting defaults (PRD §3.6) -----------------------
DEFAULT_TOLERANCE_MM = 25.0
DEFAULT_CHANGEOVER_BUFFER_MINUTES = 45

# --- Earned value (PRD §3.9) -------------------------------------------
WEATHER_TIGHT_MILESTONE_FACTOR = 0.95
RETENTION_RATE = 0.05

# --- Pagination (PRD §2.3) ---------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Canonical scenario values -----------------------------------------
TEST_DEFAULTS = {
    "PACKAGE_NAME": "Tower A Facade",
    "FLOOR_COUNT": 20,
    "TOTAL_AREA_SQM": 9000.0,
    "CONTRACT_VALUE_CENTS": 1_450_000_000,
    "UNIT_RATE_CENTS_PER_SQM": 148_733,
    "BASE_LABOR_RATE_CENTS_PER_HOUR": 9_800,
    "DESIGN_TEMP_DELTA_C": 60.0,
    "WEATHER_TIGHTNESS_DEADLINE_DATE": "2026-12-15",
    "SUPPLIER_NAME": "Vitro Flat Glass",
    "COATING_CODE": "LOWE-366",
    "QUOTED_LEAD_TIME_DAYS": 90,
    "ORDERED_LITES": 240,
    "LAB_NAME": "Chamber Labs NE",
    "LAB_CHAMBER_CAPACITY": 2,
    "LAB_ACCREDITATION_REF": "AAMA-CL-01",
    "SEAL_LICENSE_NO": "PE-44821",
    "DRAWING_SET_REF": "SD-001",
    "SUBMITTAL_TITLE": "Typical unitized panel set",
    "RIG_CODE": "HR-1",
    "RIG_CAPACITY_PANELS_PER_SHIFT": 20,
    "EMBED_LAYOUT_REF": "EL-05-N",
    "PLANNED_ANCHOR_COUNT": 72,
}

# Zone A — floor 5 NORTH, 412.37 sqm at 24.0 m, 36 panels, 320.0 budget hours.
ZONE_A = {
    "floor_number": 5,
    "elevation_label": "NORTH",
    "area_sqm": 412.37,
    "height_m": 24.0,
    "span_mm": 3200,
    "anchor_type": "SLOTTED",
    "designed_joint_mm": 22.0,
    "planned_panel_count": 36,
    "budget_crew_hours": 320.0,
}

# Zone B — floor 6 NORTH, 388.63 sqm, otherwise identical to zone A.
ZONE_B = {
    "floor_number": 6,
    "elevation_label": "NORTH",
    "area_sqm": 388.63,
    "height_m": 24.0,
    "span_mm": 3200,
    "anchor_type": "SLOTTED",
    "designed_joint_mm": 22.0,
    "planned_panel_count": 36,
    "budget_crew_hours": 320.0,
}

# The three crew days of zone A: 9.0 h then 8.0 h then 8.0 h at crew size 4.
ZONE_A_CREW_DAYS = [
    {"work_date": "2026-08-10", "crew_size": 4, "shift_hours": 9.0, "panels_installed": 10},
    {"work_date": "2026-08-11", "crew_size": 4, "shift_hours": 8.0, "panels_installed": 13},
    {"work_date": "2026-08-12", "crew_size": 4, "shift_hours": 8.0, "panels_installed": 13},
]

ZONE_B_CREW_DAYS = [
    {"work_date": "2026-08-11", "crew_size": 4, "shift_hours": 8.0, "panels_installed": 18},
]

# Opaque operator identifiers used across the scenarios.
USER_IDS = {
    "PROJECT_MANAGER": "u-pm-1",
    "DETAILER": "u-det-1",
    "ENGINEER": "u-eng-1",
    "ENGINEER_ALT": "u-eng-2",
    "ARCHITECT": "u-aor-1",
    "PROCUREMENT": "u-proc-1",
    "STRUCTURAL": "u-struct-1",
    "SUPERINTENDENT": "u-super-1",
    "QC_1": "u-qc-1",
    "QC_2": "u-qc-2",
    "QC_3": "u-qc-3",
}

# A syntactically valid UUID that is never minted by the server.
FABRICATED_UUID = "11111111-2222-4333-8444-555555555555"
