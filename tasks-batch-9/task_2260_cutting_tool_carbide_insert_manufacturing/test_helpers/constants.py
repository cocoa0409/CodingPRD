"""Domain thresholds and pinned numeric constants taken from the PRD.

Nothing here is invented: every value is a literal the PRD states for a
formula, a boundary or a budget.
"""

# ── The logical shop clock (PRD §2.5) ───────────────────────────────────────
CLOCK_STARTUP_UTC = "2026-08-01T00:00:00Z"

# ── Sintering QC (PRD §3.1) ─────────────────────────────────────────────────
SINTER_QC = {
    "MIN_DENSITY_GCC": 14.35,
    "MAX_HARDNESS_DEVIATION_HV": 75,
    "MIN_YIELD_PCT": 85.00,
}

# ── Coating (PRD §3.3) ──────────────────────────────────────────────────────
COATING = {
    "MIN_LAYERS": 1,
    "MAX_LAYERS": 5,
    "MIN_LAYER_THICKNESS_UM": 0.10,
    "MAX_LAYER_THICKNESS_UM": 8.00,
    "CHAMBER_AREA_BUDGET_CM2": 4000.00,
    "VALIDATION_MAX_ADHESION_CLASS": 2,
    "VALIDATION_THICKNESS_TOLERANCE_FRACTION": 0.15,
}

# ── Grinding wheels, cells and tolerance bands (PRD §3.4) ───────────────────
GRINDING = {
    "DRESSING_THRESHOLD_UNITS": 150,
    "MAX_DRESS_COUNT": 3,
    "CELL_SETUP_BUFFER_MINUTES": 45,
    "IT6_MAX_DEV_UM": 5.0,
    "IT7_MAX_DEV_UM": 12.0,
    "IT8_MAX_DEV_UM": 25.0,
}

# ── Engineering lead time (PRD §3.5) ────────────────────────────────────────
LEAD_TIME = {
    "BASE_CATALOG_DAYS": 5,
    "BASE_SPECIAL_DAYS": 15,
    "UNRELEASED_GEOMETRY_DAYS": 8,
    "PVD_COATING_DAYS": 4,
    "CVD_COATING_DAYS": 7,
    "UNQUALIFIED_GRADE_DAYS": 6,
    "EXPEDITE_ELIGIBLE_MAX_RAW_DAYS": 21,
    "EXPEDITE_SHAVE_DAYS": 3,
    "FLOOR_DAYS": 2,
    "SPECIAL_ORDER_REVIEW_DAYS": 5,
}

# ── Speeds-and-feeds envelope (PRD §3.5) ────────────────────────────────────
SPEEDS_FEEDS = {
    "BASELINE_VC": {"P": 220, "M": 170, "K": 150, "N": 400, "S": 60, "H": 45},
    "GRADE_FACTOR_PIVOT_PCT": 10.0,
    "GRADE_FACTOR_PER_POINT": 0.02,
    "GRADE_FACTOR_FLOOR": 0.85,
    "GRADE_FACTOR_CEILING": 1.20,
    "COATING_FACTOR_BASE": 1.10,
    "COATING_FACTOR_PER_UM": 0.02,
    "COATING_FACTOR_CEILING": 1.35,
    "RIGIDITY_FACTOR": {"RIGID": 1.00, "MEDIUM": 0.85, "WEAK": 0.70},
    "COOLANT_FACTOR": {"FLOOD": 1.00, "THROUGH_TOOL": 1.10},
    "DRY_FACTOR_UNCOATED": 0.60,
    "DRY_FACTOR_COATED": 0.75,
    "VC_CEILING": {"ROUGHING": 260, "MEDIUM": 340, "FINISHING": 420},
    "FZ_NOSE_RADIUS_MULTIPLIER": 0.35,
    "FZ_CEILING": {"ROUGHING": 0.55, "MEDIUM": 0.30, "FINISHING": 0.14},
    "AP_CEILING": {"ROUGHING": 6.0, "MEDIUM": 3.0, "FINISHING": 1.0},
}

# ── Machining trials and the wear curve (PRD §3.6) ──────────────────────────
TRIAL = {
    "FLANK_WEAR_LIMIT_UM": 300,
    "REQUIRED_LIFE_MIN": {"ROUGHING": 12.0, "MEDIUM": 18.0, "FINISHING": 25.0},
    "MAX_SURFACE_RA_UM": {"ROUGHING": 3.2, "MEDIUM": 1.6, "FINISHING": 0.8},
    "RATIO_CAP": 2.0,
    "LIFE_WEIGHT": 0.6,
    "FINISH_WEIGHT": 0.4,
    "MIN_UNITS_CONSUMED": 1,
    "MAX_UNITS_CONSUMED": 50,
}

# ── Dossier gates (PRD §3.6 / §3.7) ─────────────────────────────────────────
DOSSIER = {
    "DEFAULT_REQUIRED_TRIAL_COUNT": 2,
    "MIN_REQUIRED_TRIAL_COUNT": 2,
    "MAX_REQUIRED_TRIAL_COUNT": 8,
    "MIN_COMPOSITE_SCORE": 1.00,
    "MIN_DISTINCT_WORKPIECE_GROUPS": 2,
    "MAX_DECISION_NOTE_CHARS": 400,
}

# ── Pricing (PRD §3.8) ──────────────────────────────────────────────────────
PRICING = {
    "GRADE_SURCHARGE_NSH": 0.08,
    "COATING_SURCHARGE_PVD": 0.06,
    "COATING_SURCHARGE_CVD": 0.10,
    "SPECIAL_SURCHARGE": 0.18,
    "VOLUME_DISCOUNT_500": 0.12,
    "VOLUME_DISCOUNT_100": 0.07,
    "VOLUME_DISCOUNT_25": 0.03,
}

# ── Reconditioning (PRD §3.9) ───────────────────────────────────────────────
RECONDITION = {
    "RESERVATION_CENTS_PER_TOOL": 1850,
    "REBATE_BASIS_CENTS": 900,
    "WARRANTED_FIRST_PASS_PCT": 35.0,
    "WARRANTED_DECAY": 0.7,
    "MIN_UNITS_RECEIVED": 1,
    "MAX_UNITS_RECEIVED": 500,
}

# ── Pagination (PRD §2.3) ───────────────────────────────────────────────────
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# ── Operator identities used across the qualification chain ─────────────────
TRIAL_OPERATOR_ONE = "op-1"
TRIAL_OPERATOR_TWO = "op-2"
DOSSIER_SUBMITTER = "ae-7"
INDEPENDENT_APPROVER = "qa-3"
