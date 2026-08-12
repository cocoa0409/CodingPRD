"""Domain constants — numeric thresholds and rates named in PRD §2–§3."""

# Logical clock startup default (PRD §2.11).
CLOCK_STARTUP_DEFAULT = "2026-05-01T00:00:00Z"

THRESHOLDS = {
    # Film-build estimation (PRD §3.4).
    "FILM_TRANSFER_K": 220.0,
    "DENSITY_TIER1_MAX_PARTS": 20,
    "DENSITY_TIER2_MAX_PARTS": 40,
    "DENSITY_FACTOR_TIER1": 1.00,
    "DENSITY_FACTOR_TIER2": 0.95,
    "DENSITY_FACTOR_TIER3": 0.88,
    # Purge cost and VOC (PRD §3.8).
    "SOLVENT_COST_CENTS_PER_L": 450,
    "PURGE_FIXED_CENTS": 12000,
    "PURGE_SOLVENT_VOC_G_PER_L": 880,
    "PURGE_BUFFER_MIN": 30,
    # Theoretical VOC model (PRD §3.9).
    "SOLIDS_FRACTION": 0.35,
    "TRANSFER_EFFICIENCY": 0.95,
    # Strip emission (PRD §3.7).
    "STRIP_SOLVENT_L_PER_PART": 0.5,
    "STRIP_SOLVENT_VOC_G_PER_L": 900,
    # Rework charge (PRD §3.7).
    "STRIP_BASE_CENTS": 25000,
    "STRIP_PER_PART_CENTS": 300,
    "REPAINT_RATE_CENTS_PER_DM2": 85,
    "REWORK_MULTIPLIER": 1.33,
    "MAX_REWORK_COUNT": 2,
    # Base coat rate (PRD §3.3).
    "BASE_COAT_RATE_CENTS_PER_DM2": 110,
}

TEST_DEFAULTS = {
    "CUSTOMER_NAME": "Acme Housings",
    "COLOR_RAL9005": "RAL9005",
    "COLOR_RAL1018": "RAL1018",
    "COLOR_RAL3000": "RAL3000",
    "COLOR_RAL6005": "RAL6005",
    "LINE_NAME": "L1",
    "LINE_SPEED_FPM": 10.0,
    "HANGER_CAPACITY_PARTS": 60,
    "OVEN_NAME": "OV-1",
    "OVEN_MAX_LOADS": 2,
    "STAGE_NAME": "alkaline_clean",
    "CHEMICAL_FAMILY": "CLEANER",
    "CONC_MIN_GPL": 20.0,
    "CONC_MAX_GPL": 30.0,
    "PERIOD_START": "2026-05-01T00:00:00Z",
    "PERIOD_END": "2026-06-01T00:00:00Z",
    "PERMIT_CAP_KG": 500.0,
    "PART_QUANTITY": 100,
    "PARTS_PER_HANGER": 20,
    "PAINT_USED_LITERS": 0.95,
    # Standard spec used by most scenarios: film 18-30 um, cure 180C/20min,
    # adhesion class >= 2, impact >= 40 J, voc 320 g/L, area 12 dm2/part.
    "SPEC_FILM_MIN_UM": 18.0,
    "SPEC_FILM_MAX_UM": 30.0,
    "SPEC_CURE_METAL_TEMP_C": 180.0,
    "SPEC_CURE_MINUTES_AT_TEMP": 20,
    "SPEC_ADHESION_CLASS_MIN": 2,
    "SPEC_IMPACT_JOULES_MIN": 40.0,
    "SPEC_VOC_G_PER_L": 320.0,
    "SPEC_AREA_DM2_PER_PART": 12.0,
    # Standard slot window.
    "SLOT_START_UTC": "2026-05-05T08:00:00Z",
    "SLOT_END_UTC": "2026-05-05T10:00:00Z",
}
