"""Literal constants transcribed from the PRD's business-logic sections.

Nothing here is derived from an implementation; every value is a PRD-declared
constant, default or shared fixture literal used by the design indices.
"""

# --- Logical clock (PRD 2.4) -------------------------------------------------

CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# --- Pagination (PRD 2.3) ----------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Plant defaults (PRD 3.1) ------------------------------------------------

DEFAULT_MAX_CULLET_FRACTION = 0.30
DEFAULT_CULLET_RESTRICT_FRACTION = 0.28
DEFAULT_MAX_WIDTH_CHANGE_IN = 8.0

# --- cullet_charge_allocation (PRD 3.3) --------------------------------------

MELT_YIELD = 0.92

# --- binder_cure_index (PRD 3.2 / 3.4) --------------------------------------

CURE_TEMP_SPAN_F = 60.0
MAX_BINDER_REVISIONS = 2
DWELL_RATIO_CAP = 1.25
MIN_CURE_INDEX = 100.0

# --- permit_period_emissions (PRD 3.2 / 3.9) --------------------------------

FORMALDEHYDE_CERT_LIMIT_PPM = 300
VOC_CERT_LIMIT_G_PER_KG = 6.0

# --- packaging_compression_economics (PRD 3.2) ------------------------------

RECOVERY_FREE_RATIO = 4.0
RECOVERY_LOSS_PCT_PER_RATIO_PT = 5.0
FACED_RECOVERY_PENALTY_PCT = 2.0
RECOVERY_FLOOR_PCT = 80.0
TRUCK_VOLUME_FT3 = 3800
TRUCK_PAYLOAD_KG = 19500
TRUCK_RATE_USD = 2450.0
DECLARED_RECOVERY_MIN_PCT = 95.0
RECOVERY_PENALTY_USD_PER_PCT = 0.0012

# --- changeover_scrap_accounting (PRD 3.5) ----------------------------------

TRANSITION_BASE_MIN = 12
DENSITY_MIN_PER_PCT = 0.4
DENSITY_PURGE_CAP_MIN = 20
WIDTH_CHANGE_MIN = 8
FACING_CHANGE_MIN = 15
CHANGEOVER_PURGE_BUFFER_MIN = 30

# --- thermal_conformance_verdict (PRD 3.6) ----------------------------------

NONCONFORMANCE_SUSPEND_THRESHOLD = 2

# --- declared_value_derate (PRD 3.7) ----------------------------------------

DERATE_STEP = 0.5

# --- scrap_cullet_recovery (PRD 3.8) ----------------------------------------

LB_TO_KG = 0.45359237
FACING_MASS_FRACTION = 0.08
SCRAP_CULLET_RECOVERY = 0.85

# --- channel_allocation_waterfall (PRD 3.9) ---------------------------------

PEAK_RESERVE_PCT = 0.15
OFFPEAK_RESERVE_PCT = 0.05
PEAK_MONTHS = [3, 4, 5, 6, 7, 8, 9]
TIER_RANK = {"CONTRACT": 1, "PROGRAM": 2, "SPOT": 3}

# --- Decimal scales (PRD 2.5) -----------------------------------------------

MASS_DP = 2
AREA_DP = 2
RATIO_DP = 4
EMISSIONS_DP = 4
BALE_VOLUME_DP = 3
COST_DP = 6

# --- Shared fixture literals used by the design indices ---------------------

# Certification programs
PROGRAM_PER_SPECIMEN = {
    "code": "RCERT-PS",
    "conformance_basis": "PER_SPECIMEN",
    "r_value_tolerance": 0.30,
    "min_specimen_count": 3,
    "max_concurrent_lab_tests": 2,
    "retest_limit": 2,
    "derate_allowed": True,
}

PROGRAM_LOT_MEAN = {
    "code": "RCERT-LM",
    "conformance_basis": "LOT_MEAN",
    "r_value_tolerance": 0.30,
    "min_specimen_count": 3,
    "max_concurrent_lab_tests": 1,
    "retest_limit": 2,
    "derate_allowed": True,
}

PROGRAM_NO_DERATE = {
    "code": "RCERT-ND",
    "conformance_basis": "PER_SPECIMEN",
    "r_value_tolerance": 0.30,
    "min_specimen_count": 3,
    "max_concurrent_lab_tests": 2,
    "retest_limit": 2,
    "derate_allowed": False,
}

# Plant
PLANT_NEWARK = {
    "name": "Newark Forming Plant",
    "site_code": "NWK",
    "oven_zone_count": 4,
    "oven_length_ft": 120.0,
    "production_line_count": 2,
    "max_cullet_fraction": 0.30,
    "cullet_restrict_fraction": 0.28,
    "max_width_change_in": 8.0,
    "permit_number": "NJ-AIR-4471",
    "formaldehyde_allowance_kg": 0.200,
    "voc_allowance_kg": 12.0,
}

# Binder formulations
BINDER_FORMALDEHYDE_FREE = {
    "code": "BF-FREE-1",
    "formaldehyde_free": True,
    "formaldehyde_ppm": 0,
    "voc_g_per_kg": 3.2,
    "min_cure_temp_f": 420.0,
    "min_dwell_s": 150.0,
    "loi_target_pct": 4.5,
}

BINDER_PHENOLIC = {
    "code": "BF-PHEN-1",
    "formaldehyde_free": False,
    "formaldehyde_ppm": 250,
    "voc_g_per_kg": 4.1,
    "min_cure_temp_f": 430.0,
    "min_dwell_s": 160.0,
    "loi_target_pct": 5.0,
}

# Zone setpoints matching PLANT_NEWARK's four oven zones
ZONE_SETPOINTS_4 = [440.0, 450.0, 450.0, 440.0]

# SKU literals shared by the design indices (partial payloads: the three foreign
# keys are supplied by the caller).
SKU_PL_A = {
    "sku": "R13-15-UF",
    "form": "BATT",
    "density_pcf": 0.80,
    "facing_type": "UNFACED",
    "width_in": 15.0,
    "thickness_in": 3.5,
    "declared_r_value": 13.0,
    "bag_sqft": 88.0,
    "bale_volume_ft3": 21.0,
    "bale_mass_kg": 12.5,
    "compression_ratio": 6.0,
    "mass_rate_kg_per_min": 34.5,
}

SKU_PL_B = {
    "sku": "R19-23-KR",
    "form": "BATT",
    "density_pcf": 1.20,
    "facing_type": "KRAFT",
    "width_in": 23.0,
    "thickness_in": 6.25,
    "declared_r_value": 19.0,
    "bag_sqft": 49.0,
    "bale_volume_ft3": 25.5,
    "bale_mass_kg": 15.0,
    "compression_ratio": 5.0,
    "mass_rate_kg_per_min": 41.0,
}

SKU_PL_C = dict(SKU_PL_A, sku="R13-16-UF-LM", width_in=16.0)

ZONES_470 = [470.0, 470.0, 470.0, 470.0]
ZONES_480 = [480.0, 480.0, 480.0, 480.0]
