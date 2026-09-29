"""Domain thresholds and numeric constants stated by the PRD."""

# ─── Inventory and vessel physics ─────────────────────────────────────────

KG_PER_L_PER_BAR = 0.00008
MIN_HIGH_BANK_DELIVERABLE_KG = 10.000
TERMINAL_BAR_H70 = 875.00
TERMINAL_BAR_H35 = 438.00
TERMINAL_BAR_BY_PRESSURE_CLASS = {
    "H70": TERMINAL_BAR_H70,
    "H35": TERMINAL_BAR_H35,
}

# ─── Metering correction ──────────────────────────────────────────────────

REF_TEMP_C = 20.0
REF_PRESSURE_BAR = 700.00
TEMP_COEFF_PER_C = 0.00040
PRESSURE_COEFF_PER_BAR = -0.00002
METER_TOLERANCE_PCT = 1.500

# ─── Precool requirement table ────────────────────────────────────────────

HOT_BAND_ABOVE_C = 30.0
MILD_BAND_ABOVE_C = 10.0
MC_FORMULA_RELIEF_C = 5.0
REQUIRED_PRECOOL_TABLE_C = {
    ("H70", "HOT"): -40.0,
    ("H70", "MILD"): -33.0,
    ("H70", "COLD"): -26.0,
    ("H35", "HOT"): -33.0,
    ("H35", "MILD"): -26.0,
    ("H35", "COLD"): -17.0,
}

# ─── Carbon intensity ─────────────────────────────────────────────────────

H2_LHV_MJ_PER_KG = 120.0
COMPRESSION_ADDER_G_PER_KG = 300.0
NG_TOTAL_G_PER_MMBTU = 61260.0
CI_BENCHMARK_GCO2E_PER_MJ = 79.10
EER = 3.4

# ─── Incentive administrative fee tiers, keyed on gross credits ───────────

ADMIN_TIER_HIGH_MT = 3.600
ADMIN_TIER_MID_MT = 1.200
ADMIN_RATE_HIGH = 0.030
ADMIN_RATE_MID = 0.020
ADMIN_RATE_LOW = 0.010

# ─── Purity limits in ppm; an analyte fails only when strictly greater ────

PURITY_LIMITS_PPM = {
    "total_hydrocarbons_ppm": 2.000,
    "water_ppm": 5.000,
    "oxygen_ppm": 5.000,
    "nitrogen_ppm": 100.000,
    "carbon_monoxide_ppm": 0.200,
    "carbon_dioxide_ppm": 2.000,
    "total_sulfur_ppm": 0.004,
    "ammonia_ppm": 0.100,
    "helium_ppm": 300.000,
}
MANDATORY_ANALYTES = (
    "total_hydrocarbons_ppm",
    "water_ppm",
    "oxygen_ppm",
    "nitrogen_ppm",
    "carbon_monoxide_ppm",
    "carbon_dioxide_ppm",
    "total_sulfur_ppm",
)
OPTIONAL_ANALYTES = ("ammonia_ppm", "helium_ppm")

# ─── Operational thresholds ───────────────────────────────────────────────

INSPECTION_GRACE_DAYS = 30
MIN_TRAINED_RESPONDERS = 2
MAX_RESCHEDULES = 2
MAX_REVISION_ROUNDS = 2
LOT_CONSUMED_FRACTION = 0.900
CONTRACT_CHANGEOVER_BUFFER_HOURS = 24
DAILY_BOILOFF_RATE = 0.003

# ─── Logical clock ────────────────────────────────────────────────────────

DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# ─── Pagination ───────────────────────────────────────────────────────────

DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0

# ─── Values shared across the recurring test scenarios ────────────────────

TEST_DEFAULTS = {
    "MIN_UPTIME_PCT": 99.000,
    "PENALTY_PER_POINT_CENTS": 250000,
    "INITIAL_HOLDBACK_CENTS": 500000,
    "STORAGE_CAPACITY_KG": 900.000,
    "RESERVE_FLOOR_KG": 100.000,
    "NOZZLE_COUNT": 4,
    "OFFLOAD_BAY_COUNT": 1,
}

# The three-vessel cascade bank used by most scenarios.  Commissioning it seeds
# 45.600 + 56.000 + 120.000 = 221.600 kg of on-site inventory, 160.000 kg of
# total deliverable mass and 36.000 kg of high-bank deliverable mass.
STANDARD_BANK = (
    {
        "bank_tier": "HIGH",
        "water_volume_l": 600.000,
        "mawp_bar": 1000.00,
        "min_residual_bar": 200.00,
        "initial_pressure_bar": 950.00,
    },
    {
        "bank_tier": "MEDIUM",
        "water_volume_l": 1000.000,
        "mawp_bar": 1000.00,
        "min_residual_bar": 150.00,
        "initial_pressure_bar": 700.00,
    },
    {
        "bank_tier": "LOW",
        "water_volume_l": 5000.000,
        "mawp_bar": 1000.00,
        "min_residual_bar": 100.00,
        "initial_pressure_bar": 300.00,
    },
)
STANDARD_BANK_ONSITE_KG = 221.600
STANDARD_BANK_TOTAL_DELIVERABLE_KG = 160.000
STANDARD_BANK_HIGH_DELIVERABLE_KG = 36.000

# ─── The recurring production chain ───────────────────────────────────────
#
# One 1000.000 kg electrolysis lot drawing 52000.0 kWh under a grid at
# 385000.00 gCO2e/MWh.  Annual-average accounting deducts 62.500 % renewable
# and hourly matching deducts only 41.000 %, so the same lot carries two
# different certified intensities:
#
#   annual   = 52000 x 385 x (1 - 0.625) + 1000 x 300 = 7807500 g over
#              1000 x 120 = 120000 MJ                 -> 65.0625 -> 65.06
#   hourly   = 52000 x 385 x (1 - 0.410) + 1000 x 300 = 12111800 g over
#              120000 MJ                              -> 100.9316 -> 100.93

CANONICAL_ASSET = {
    "pathway": "PEM_ELECTROLYSIS",
    "nameplate_kg_per_day": 1200.000,
    "ccs_capture_rate": 0.0000,
    "operator_org": "Harbor H2 Production",
}
CANONICAL_CONTRACT = {
    "grid_ci_gco2e_per_mwh": 385000.00,
    "annual_renewable_pct": 62.500,
    "hourly_matched_renewable_pct": 41.000,
    "hourly_matching_enabled": False,
    "effective_from": "2026-01-01T00:00:00Z",
    "effective_to": "2027-01-01T00:00:00Z",
}
CANONICAL_LOT = {
    "mass_kg": 1000.000,
    "energy_consumed_kwh": 52000.0,
    "feedstock_consumed_mmbtu": 0.000,
    "carryover_kg": 0.000,
    "production_start_at": "2026-07-20T00:00:00Z",
    "production_end_at": "2026-07-21T00:00:00Z",
}
# Sampled after the lot's production_end_at, as the sampling rule requires.
CANONICAL_PURITY = {
    "sampled_at": "2026-07-22T00:00:00Z",
    "total_hydrocarbons_ppm": 1.000,
    "water_ppm": 4.000,
    "oxygen_ppm": 3.000,
    "nitrogen_ppm": 50.000,
    "carbon_monoxide_ppm": 0.150,
    "carbon_dioxide_ppm": 1.000,
    "total_sulfur_ppm": 0.004,
    "ammonia_ppm": 0.050,
    "helium_ppm": 100.000,
}
CANONICAL_LOT_CI_ANNUAL = 65.06
CANONICAL_LOT_CI_HOURLY = 100.93

# A smaller 300.000 kg lot at 15600.0 kWh under a 50.000 % renewable grid:
#   15600 x 385 x 0.5 + 300 x 300 = 3093000 g over 36000 MJ -> 85.9166 -> 85.92
SMALL_CONTRACT = {
    "grid_ci_gco2e_per_mwh": 385000.00,
    "annual_renewable_pct": 50.000,
    "hourly_matched_renewable_pct": 41.000,
    "hourly_matching_enabled": False,
    "effective_from": "2026-01-01T00:00:00Z",
    "effective_to": "2027-01-01T00:00:00Z",
}
SMALL_LOT = {
    "mass_kg": 300.000,
    "energy_consumed_kwh": 15600.0,
    "feedstock_consumed_mmbtu": 0.000,
    "carryover_kg": 0.000,
    "production_start_at": "2026-07-20T00:00:00Z",
    "production_end_at": "2026-07-21T00:00:00Z",
}
SMALL_LOT_CI_ANNUAL = 85.92
# Half of every purity limit, sampled after the small lot's production end.
HALF_LIMIT_PURITY = {
    "sampled_at": "2026-07-21T06:00:00Z",
    "total_hydrocarbons_ppm": 1.000,
    "water_ppm": 2.500,
    "oxygen_ppm": 2.500,
    "nitrogen_ppm": 50.000,
    "carbon_monoxide_ppm": 0.100,
    "carbon_dioxide_ppm": 1.000,
    "total_sulfur_ppm": 0.002,
    "ammonia_ppm": 0.050,
    "helium_ppm": 150.000,
}
