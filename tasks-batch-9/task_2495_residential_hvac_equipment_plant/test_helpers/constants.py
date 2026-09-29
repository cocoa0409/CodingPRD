"""Domain thresholds and calculation constants stated in the PRD."""

# --- Logical plant clock (PRD §2.4) -----------------------------------------
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# A well-formed UUID token that names no stored row.
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"


# --- Leak-test limits (PRD §3.8) -------------------------------------------
LEAK_TEST = {
    "HELIUM_BASE_LIMIT_G_PER_YEAR": 3.000,
    "DECAY_ALLOWANCE_KPA_PER_15MIN": 2.00,
    "A2L_STRICTNESS_FACTOR": 0.500,
    "A1_STRICTNESS_FACTOR": 1.000,
    "MIN_PRESSURE_DECAY_HOLD_MINUTES": 15,
}


# --- Run-test performance verdict (PRD §3.8) -------------------------------
RUN_TEST = {
    "RATING_AMBIENT_C": 35.0,
    "AMBIENT_COEFFICIENT_PER_C": 0.0040,
    "MIN_EFFICIENCY_TOLERANCE": 0.90,
}

# Jointly keyed by the platform's efficiency_tier and the program's
# flammability_class; both tolerances must come from the same cell.
CAPACITY_TOLERANCE_TABLE = {
    ("STANDARD", "A1"): 0.9500,
    ("STANDARD", "A2L"): 0.9400,
    ("HIGH", "A1"): 0.9700,
    ("HIGH", "A2L"): 0.9600,
    ("PREMIUM", "A1"): 0.9800,
    ("PREMIUM", "A2L"): 0.9800,
}

EFFICIENCY_TOLERANCE_TABLE = {
    ("STANDARD", "A1"): 0.9300,
    ("STANDARD", "A2L"): 0.9200,
    ("HIGH", "A1"): 0.9500,
    ("HIGH", "A2L"): 0.9400,
    ("PREMIUM", "A1"): 0.9600,
    ("PREMIUM", "A2L"): 0.9600,
}


# --- Component allocation (PRD §3.5) ---------------------------------------
ALLOCATION = {
    "MIN_GRANT_UNITS": 1,
    "MIN_DENOMINATOR_UNITS": 1,
}


# --- Pre-season carrying cost (PRD §3.7) -----------------------------------
CARRYING_COST = {
    "RATE_CENTS_PER_PALLET_WEEK": 1165,
    "DAYS_PER_WEEK": 7,
}


# --- Warranty posture and supplier derate (PRD §3.9) -----------------------
WARRANTY = {
    "CAPA_THRESHOLD_PCT": 5.00,
    "DESIGN_CHANGE_THRESHOLD_PCT": 10.00,
    "MIN_UNITS_FOR_POSTURE": 20,
    "MIN_CLAIMS_FOR_POSTURE": 3,
}

# Keyed by component_type and the band the rolling_claim_rate_pct falls into.
# Bands are inclusive at the bottom and exclusive at the top.
DERATE_TABLE = {
    "COMPRESSOR": {"BAND_5_TO_7_5": 25, "BAND_7_5_TO_10": 50, "BAND_10_PLUS": 100},
    "CONTROL_BOARD": {"BAND_5_TO_7_5": 25, "BAND_7_5_TO_10": 25, "BAND_10_PLUS": 50},
}


# --- Test cell (PRD §3.8) --------------------------------------------------
TEST_CELL = {
    "DEFAULT_COOLDOWN_MINUTES": 30,
}


# --- Pagination (PRD §2.3) -------------------------------------------------
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
}


# --- Canonical test literals reused across setups -------------------------
A2L_PROGRAM_DEFAULTS = {
    "refrigerant_code": "R-454B",
    "gwp": 466,
    "flammability_class": "A2L",
    "manufacture_cutoff_utc": "2027-01-01T00:00:00Z",
    "sell_through_deadline_utc": "2027-07-01T00:00:00Z",
}

A1_PROGRAM_DEFAULTS = {
    "refrigerant_code": "R-410A",
    "gwp": 2088,
    "flammability_class": "A1",
    "manufacture_cutoff_utc": "2027-01-01T00:00:00Z",
    "sell_through_deadline_utc": "2027-07-01T00:00:00Z",
}

SOUTHEAST_STANDARD_DEFAULTS = {
    "region_code": "SOUTHEAST",
    "min_seer2_standard": 14.30,
    "min_seer2_high": 15.20,
    "min_seer2_premium": 16.00,
    "effective_from_utc": "2026-01-01T00:00:00Z",
}

NORTHEAST_STANDARD_DEFAULTS = {
    "region_code": "NORTHEAST",
    "min_seer2_standard": 15.20,
    "min_seer2_high": 16.00,
    "min_seer2_premium": 17.00,
    "prohibits_flammable_refrigerant": True,
    "effective_from_utc": "2026-01-01T00:00:00Z",
}

HIGH_A2L_PLATFORM_DEFAULTS = {
    "model_code": "HX-3600-A2L",
    "efficiency_tier": "HIGH",
    "rated_capacity_btuh": 36000,
    "rated_eer": 12.50,
    "rated_seer2": 15.80,
    "compressor_part_number": "CMP-5T-A2L",
    "control_board_part_number": "CTL-9X",
    "max_charge_grams": 1800,
}

STANDARD_A1_PLATFORM_DEFAULTS = {
    "model_code": "LX-2400-A1",
    "efficiency_tier": "STANDARD",
    "rated_capacity_btuh": 24000,
    "rated_eer": 11.80,
    "rated_seer2": 14.60,
    "compressor_part_number": "CMP-2T-A1",
    "control_board_part_number": "CTL-4X",
}
