"""Domain constants for the pump manufacturing and hydraulic testing API.

Every value here is transcribed from the PRD prose (sections 2.5, 2.9, 2.10,
2.11 and the nine workflow subsections of section 3). Nothing is invented.
"""

# ── Logical clock ────────────────────────────────────────────────────────────
# PRD 2.4: the clock starts at this instant on a cold boot and only moves when
# the platform administrator sets it.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# ── Money / rounding ─────────────────────────────────────────────────────────
# PRD 2.5: every monetary and derived numeric value is rounded half up.
MONEY_DP = 2

# ── Test grade table (PRD 2.11) ──────────────────────────────────────────────
# head tolerance percent, efficiency tolerance percent, minimum measured points
GRADE_TABLE = {
    "GRADE_1B": {"head_tol_pct": 3.0, "eff_tol_pct": 3.0, "min_points": 5},
    "GRADE_2B": {"head_tol_pct": 5.0, "eff_tol_pct": 5.0, "min_points": 5},
    "GRADE_3B": {"head_tol_pct": 7.0, "eff_tol_pct": 7.0, "min_points": 3},
}

# ── Hydraulic selection ──────────────────────────────────────────────────────
HYDRAULIC_POWER_COEFF = 0.00272407
MOTOR_MARGIN = 1.10
EFFICIENCY_FLOOR_PCT = 20.0
OFF_BEP_PENALTY_CAP = 12.0
OFF_BEP_PENALTY_COEFF = 40.0
TRIM_PENALTY_COEFF = 0.45

# Viscosity de-rating factor, keyed on the upper edge of each band (inclusive).
VISCOSITY_FACTOR_TIERS = [
    (20.0, 1.00),
    (100.0, 0.94),
    (400.0, 0.86),
]
VISCOSITY_FACTOR_ABOVE_TOP = 0.74

# Abrasive penalty base by service class; ABRASIVE and CORROSIVE_ABRASIVE also
# add 0.30 for each percent of solids.
ABRASIVE_PENALTY_BASE = {
    "CLEAN": 0.0,
    "CORROSIVE": 0.0,
    "ABRASIVE": 2.5,
    "CORROSIVE_ABRASIVE": 3.5,
}
ABRASIVE_PENALTY_PER_SOLIDS_PCT = 0.30

# ── NPSH ─────────────────────────────────────────────────────────────────────
NPSHR_FLOW_EXPONENT = 1.6
MIN_NPSH_MARGIN_M = 0.60
NPSH_TEST_TOLERANCE_M = 0.30

# Safety factor chosen from the PROVISIONAL margin, upper edge exclusive.
NPSH_SAFETY_TIERS = [
    (0.5, 1.35),
    (1.5, 1.25),
    (3.0, 1.15),
]
NPSH_SAFETY_ABOVE_TOP = 1.10

# ── Balance and clearance ────────────────────────────────────────────────────
ISO1940_COEFF = 9549
BALANCE_GRADE_G = {"G1_0": 1.0, "G2_5": 2.5, "G6_3": 6.3}
CLEARANCE_BAND_WIDTH_MM = 0.15

# ── Casting ──────────────────────────────────────────────────────────────────
PATTERN_DEFECT_WEIGHT = 2
MAX_REWORK_CYCLES = 2

# ── Kit allocation handling tiers, keyed on parts_extended upper edge ────────
HANDLING_RATE_TIERS = [
    (1000.0, 0.12),
    (5000.0, 0.08),
    (20000.0, 0.05),
]
HANDLING_RATE_ABOVE_TOP = 0.03

# ── Warranty ─────────────────────────────────────────────────────────────────
WARRANTY_MONTHS = 36
ADMIN_RATE = 0.075
# Coverage factor keyed on months_since_ship upper edge (inclusive).
COVERAGE_FACTOR_TIERS = [
    (12, 1.00),
    (24, 0.60),
    (36, 0.30),
]
APPLICATION_ERROR_FLAG_ORDER = [
    "SOLIDS_EXCEEDS_CONFIG",
    "VISCOSITY_EXCEEDS_CONFIG",
    "NPSHA_BELOW_CERTIFIED",
    "SPEED_ABOVE_RATED",
]

# ─────────────────────────────────────────────────────────────────────────────
# Canonical reference world.  The design indices build almost every scenario on
# top of one foundry, one pump model, one pattern and one material/seal config;
# these literals keep the derived numbers below reproducible.
# ─────────────────────────────────────────────────────────────────────────────

FOUNDRY_NORTH = {
    "foundry_code": "FDY-NORTH",
    "name": "North Iron Works",
    "approved_alloys": ["CI_GG25", "DUPLEX_S31803"],
    "concurrent_pour_capacity": 2,
}

MODEL_HSC_14 = {
    "model_code": "HSC-14",
    "generation": 2,
    "interchange_group": "IG-HSC-14",
    "max_impeller_diameter_mm": 355.0,
    "min_impeller_diameter_mm": 300.0,
    "shutoff_head_m": 92.0,
    "bep_flow_m3h": 300.0,
    "bep_head_m": 72.0,
    "bep_efficiency_pct": 82.0,
    "npshr_at_bep_m": 4.20,
    "rated_speed_rpm": 2950,
    "max_flow_m3h": 380.0,
    "rotor_mass_kg": 68.0,
    "balance_grade": "G6_3",
}

MODEL_VTP_08 = {
    "model_code": "VTP-08",
    "generation": 1,
    "interchange_group": "IG-VTP-08",
    "max_impeller_diameter_mm": 250.0,
    "min_impeller_diameter_mm": 200.0,
    "shutoff_head_m": 60.0,
    "bep_flow_m3h": 120.0,
    "bep_head_m": 45.0,
    "bep_efficiency_pct": 74.0,
    "npshr_at_bep_m": 3.00,
    "rated_speed_rpm": 1480,
    "max_flow_m3h": 160.0,
    "rotor_mass_kg": 40.0,
    "balance_grade": "G2_5",
}

PATTERN_HSC14_A = {"pattern_code": "PAT-HSC14-A", "wear_threshold": 20}

CONFIG_CI_P11 = {
    "config_code": "MSC-CI-P11",
    "casing_material": "CI_GG25",
    "impeller_material": "CI_GG25",
    "seal_type": "SINGLE_CARTRIDGE",
    "flush_plan": "API_PLAN_11",
    "service_class": "CLEAN",
    "max_solids_pct": 0.0,
    "max_viscosity_cst": 50.0,
    "max_chloride_ppm": 200.0,
    "max_temp_c": 120.0,
    "min_running_clearance_mm": 0.30,
}

CONFIG_DX_P32 = {
    "config_code": "MSC-DX-P32",
    "casing_material": "DUPLEX_S31803",
    "impeller_material": "DUPLEX_S31803",
    "seal_type": "DOUBLE_CARTRIDGE",
    "flush_plan": "API_PLAN_32",
    "service_class": "ABRASIVE",
    "max_solids_pct": 8.0,
    "max_viscosity_cst": 200.0,
    "max_chloride_ppm": 5000.0,
    "max_temp_c": 110.0,
    "min_running_clearance_mm": 0.45,
}

# Duty point 265.0 m3/h at 74.0 m against HSC-14 + MSC-CI-P11.
DUTY_APP_1001 = {
    "application_code": "APP-1001",
    "customer_name": "Delta Refining",
    "duty_flow_m3h": 265.0,
    "duty_head_m": 74.0,
    "npsha_available_m": 5.00,
    "specific_gravity": 1.00,
    "viscosity_cst": 1.2,
    "solids_pct": 0.0,
    "chloride_ppm": 150.0,
    "process_temp_c": 60.0,
    "min_efficiency_pct": 74.0,
    "test_grade": "GRADE_1B",
    "witness_required": True,
    "service_class_required": "CLEAN",
}

# An abrasive slurry duty: 230.0 m3/h at 60.0 m against HSC-14 + MSC-DX-P32,
# exercising the off-BEP, trim, abrasive and viscosity terms all at once.
DUTY_APP_2001 = {
    "application_code": "APP-2001",
    "customer_name": "Tailings Co",
    "duty_flow_m3h": 230.0,
    "duty_head_m": 60.0,
    "npsha_available_m": 6.00,
    "specific_gravity": 1.25,
    "viscosity_cst": 45.0,
    "solids_pct": 6.0,
    "chloride_ppm": 3500.0,
    "process_temp_c": 95.0,
    "min_efficiency_pct": 66.0,
    "test_grade": "GRADE_2B",
    "witness_required": False,
    "service_class_required": "ABRASIVE",
}

# Derived Selection values for DUTY_APP_1001 against MODEL_HSC_14.
SEL_1001_TRIMMED_DIAMETER_MM = 350.3
SEL_1001_PREDICTED_HEAD_M = 73.97
SEL_1001_PREDICTED_EFFICIENCY_PCT = 80.96
SEL_1001_NPSHR_CATALOG_M = 3.52
SEL_1001_NPSH_PROVISIONAL_MARGIN_M = 1.48
SEL_1001_NPSH_SAFETY_FACTOR = 1.25
SEL_1001_NPSHR_CERTIFIED_M = 4.40
SEL_1001_NPSH_MARGIN_M = 0.60
# npshr_catalog_m + NPSH_TEST_TOLERANCE_M
SEL_1001_NPSH_VERIFICATION_LIMIT_M = 3.82

# BuildOrder ISO 1940 allowance for G6_3 / 68.0 kg / 2950 rpm.
BUILD_ALLOWABLE_UNBALANCE_G_MM = 1386.71

# Five measured points used by the golden test run.  Each entry is
# (measured_flow_m3h, measured_head_m, measured_power_kw) and the NPSH point
# carries its own measured_npsh3_m.
GOLDEN_CURVE_POINTS = [
    {"measured_flow_m3h": 150.0, "measured_head_m": 82.0, "measured_power_kw": 52.0},
    {"measured_flow_m3h": 200.0, "measured_head_m": 78.5, "measured_power_kw": 58.0},
    {
        "measured_flow_m3h": 250.0,
        "measured_head_m": 73.5,
        "measured_power_kw": 63.5,
        "measured_npsh3_m": 3.30,
        "is_npsh_point": True,
    },
    {"measured_flow_m3h": 280.0, "measured_head_m": 69.0, "measured_power_kw": 66.5},
    {"measured_flow_m3h": 310.0, "measured_head_m": 63.0, "measured_power_kw": 68.0},
]

# The golden points above were measured under speed: at 2900 rpm against the
# model's rated 2950 rpm, so the two correction bases diverge.
UNDERSPEED_TEST_SPEED_RPM = 2900

# The same rig read at rated speed, so speed_ratio is exactly 1.0 and the
# reported curve equals the measured curve.  Guarantee flow 265.0 lands on a
# measured point, head 74.0.
GOLDEN_CURVE_POINTS_AT_RATED = [
    {"measured_flow_m3h": 150.0, "measured_head_m": 84.0, "measured_power_kw": 55.0},
    {"measured_flow_m3h": 200.0, "measured_head_m": 80.5, "measured_power_kw": 61.0},
    {
        "measured_flow_m3h": 265.0,
        "measured_head_m": 74.0,
        "measured_power_kw": 67.21,
        "measured_npsh3_m": 3.40,
        "is_npsh_point": True,
    },
    {"measured_flow_m3h": 300.0, "measured_head_m": 70.0, "measured_power_kw": 69.5},
    {"measured_flow_m3h": 330.0, "measured_head_m": 65.0, "measured_power_kw": 71.0},
]

# Repair kit that exactly covers HSC-14 generation 2.
KIT_HSC14_G2 = {
    "kit_code": "RK-HSC14-G2",
    "interchange_group": "IG-HSC-14",
    "gen_min": 2,
    "gen_max": 2,
    "preferred_generation": 2,
    "substitution_penalty_pct": 0.0,
    "unit_price": 980.00,
    "support_window_start": "2026-01-01T00:00:00Z",
    "support_window_end": "2029-01-01T00:00:00Z",
}

PACKAGE_BP_14A = {
    "baseplate_code": "BP-14A",
    "motor_kw": 75.0,
    "motor_frame": "280M",
    "control_type": "VFD",
    "promised_ship_date": "2026-09-20T00:00:00Z",
}

DEFAULT_ACTUAL_SHIP_DATE = "2026-09-15T00:00:00Z"
# 17 whole months after DEFAULT_ACTUAL_SHIP_DATE, so coverage_factor is 0.60.
CLOCK_SEVENTEEN_MONTHS_AFTER_SHIP = "2028-03-01T00:00:00Z"

DEFAULT_POUR_WINDOW_START = "2026-08-05T00:00:00Z"
DEFAULT_POUR_WINDOW_END = "2026-08-10T00:00:00Z"
