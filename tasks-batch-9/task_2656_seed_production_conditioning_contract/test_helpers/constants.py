"""Numeric thresholds and shared literal defaults drawn from the contract."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# System-wide numeric constants
# ---------------------------------------------------------------------------

THRESHOLDS = {
    # One clean seed unit is 25.0 kg of clean seed.
    "UNIT_KG": 25.0,
    # Moisture above 12.0 percent is docked at 1.5 percent per moisture point.
    "MOISTURE_BASE_PCT": 12.0,
    "MOISTURE_SHRINK_FACTOR": 1.5,
    # Decay-weighted eligibility.
    "HISTORY_BASE_RISK": 100.0,
    "DECAY_FACTOR": 0.5,
    "ISOLATION_RISK_PER_M": 0.5,
    "DECAY_ELIGIBILITY_MAX_SCORE": 25.0,
    # Rogueing is only orderable while the worst exceedance ratio is within 3x.
    "ROGUEABLE_MULTIPLE": 3.0,
    # Quality price adjustment clamp.
    "ADJ_CAP_PCT": 8.0,
    "ADJ_FLOOR_PCT": -35.0,
    # Grower compliance standing ladder.
    "WATCH_AT_FLAGS": 2,
    "SUSPEND_AT_FLAGS": 4,
    # Inspector workload ceiling per calendar date.
    "INSPECTOR_DAILY_CAPACITY": 2,
}

# Quality price adjustment steps.
GERM_ADJUSTMENT = {"HIGH_PCT": 95.0, "HIGH_ADJ": 6.0, "MID_PCT": 90.0, "MID_ADJ": 2.0, "LOW_ADJ": 0.0}
PURITY_ADJUSTMENT = {"HIGH_PCT": 99.5, "HIGH_ADJ": 2.0, "MID_PCT": 98.0, "MID_ADJ": 0.0, "LOW_ADJ": -4.0}
WEED_ADJUSTMENT = {"CLEAN_ADJ": 0.0, "LOW_MAX": 10, "LOW_ADJ": -3.0, "MID_MAX": 30, "MID_ADJ": -9.0}

# Advance recovery cap tiers, keyed on provisional_net_cents with inclusive
# lower bounds and evaluated from the top down.
RECOVERY_CAP_TIERS = [
    (5_000_000, 100.0),
    (2_000_000, 60.0),
    (500_000, 35.0),
    (0, 15.0),
]

# Certification verdict gate: weed seeds per kilogram ceiling.
MAX_WEED_SEED_COUNT_PER_KG = 30

# ---------------------------------------------------------------------------
# Shared literal defaults used to build reference data
# ---------------------------------------------------------------------------

TEST_DEFAULTS = {
    # Logical clock
    "INITIAL_CLOCK": "2026-08-01T00:00:00Z",
    "INSPECTION_CLOCK": "2026-08-20T09:00:00Z",
    "HARVEST_CLOCK": "2026-09-14T00:00:00Z",
    # Variety
    "CROP_KIND": "WHEAT",
    "VARIETY_NAME": "HRW-Sable",
    "SECOND_VARIETY_NAME": "SRW-Corvina",
    "MAX_SEED_CLASS": "CERTIFIED",
    "ISOLATION_MIN_M": 200.0,
    "RESTRICTED_PRIOR_CROP_KINDS": ["WHEAT", "TRITICALE"],
    "RESTRICTED_PRIOR_CROP_YEARS": 3,
    "GERMINATION_MIN_PCT": 85.0,
    "PURITY_MIN_PCT": 97.0,
    "MAX_OFF_TYPE_PER_10000": 10.0,
    "MAX_RESTRICTED_WEED_PER_10000": 5.0,
    "MAX_DISEASE_INCIDENCE_PCT": 2.0,
    "MAX_ROGUEING_ROUNDS": 2,
    "ESTIMATED_CONDITIONING_SHRINK_PCT": 8.0,
    "GERM_VALIDITY_DAYS": 270,
    "MAX_CARRYOVER_GENERATIONS": 2,
    # Grower
    "GROWER_NAME": "Prairie Ridge Farms",
    "REGION_CODE": "ND-07",
    "CONTACT_EMAIL": "ops@prairieridge.example",
    "SECOND_GROWER_NAME": "Coteau Seed Co",
    "SECOND_REGION_CODE": "ND-11",
    "SECOND_CONTACT_EMAIL": "ops@coteauseed.example",
    # Production field
    "FIELD_CODE": "F-North-12",
    "ACRES": 320.0,
    "ISOLATION_DISTANCE_M": 250.0,
    # History
    "HISTORY_CROP_KIND": "CANOLA",
    "HISTORY_CROP_YEAR": 2024,
    # Contract
    "SEASON_YEAR": 2026,
    "SEED_CLASS": "CERTIFIED",
    "CONTRACTED_ACRES": 300.0,
    "BASE_PRICE_PER_UNIT_CENTS": 1850,
    "CONDITIONING_CHARGE_PER_UNIT_CENTS": 220,
    "ADVANCE_TOTAL_CENTS": 1_200_000,
    "PLANTED_ON": "2026-04-15",
    # Inspection (a comfortably passing field walk)
    "INSPECTED_ON": "2026-08-20",
    "SAMPLED_PLANTS": 20000,
    "OFF_TYPE_PLANTS": 12,
    "RESTRICTED_WEED_PLANTS": 4,
    "DISEASED_PLANTS": 100,
    "ISOLATION_VERIFIED_M": 250.0,
    # Equipment
    "EQUIPMENT_CODE": "CMB-7",
    "SECOND_EQUIPMENT_CODE": "CMB-8",
    "EQUIPMENT_KIND": "COMBINE",
    "EQUIPMENT_CLEANOUT_MINUTES_REQUIRED": 45,
    "CLEANED_AT": "2026-09-09T18:00:00Z",
    # Conditioning line
    "LINE_CODE": "LN-1",
    "LINE_CLEANOUT_MINUTES_REQUIRED": 60,
    "CAPACITY_KG_PER_HOUR": 8000.0,
    # Harvest
    "HARVEST_WINDOW_START": "2026-09-10T08:00:00Z",
    "HARVEST_WINDOW_END": "2026-09-10T18:00:00Z",
    "GROSS_WEIGHT_KG": 41000.0,
    "MOISTURE_PCT": 14.5,
    "BAG_SIZE_KG": 25.0,
    # Conditioning runs on the golden chain
    "CLEANING_WINDOW_START": "2026-09-12T06:00:00Z",
    "CLEANING_WINDOW_END": "2026-09-12T12:00:00Z",
    "CLEANING_OUTPUT_KG": 37800.0,
    "SIZING_WINDOW_START": "2026-09-12T13:00:00Z",
    "SIZING_WINDOW_END": "2026-09-12T17:00:00Z",
    "SIZING_OUTPUT_KG": 36000.0,
    "BAGGING_WINDOW_START": "2026-09-13T06:00:00Z",
    "BAGGING_WINDOW_END": "2026-09-13T10:00:00Z",
    "BAGGING_OUTPUT_KG": 34501.25,
    # Sampling and results
    "SAMPLED_ON": "2026-09-14",
    "TESTED_AT": "2026-09-14T00:00:00Z",
    "RESULT_GERMINATION_PCT": 96.0,
    "RESULT_PURITY_PCT": 99.6,
    "RESULT_INERT_PCT": 0.3,
    "RESULT_WEED_SEED_COUNT_PER_KG": 0,
    # Tagging
    "TAG_CLASS": "CERTIFIED",
    "TAG_BAG_COUNT": 1380,
    # Settlement
    "PAYMENT_REFERENCE": "ACH-2026-0914-001",
    # Treatment product
    "PRODUCT_CODE": "TRT-100",
    "EPA_REGISTRATION_NUMBER": "EPA-12345-67",
    "ALLOWED_CROP_KINDS": ["WHEAT"],
    "MAX_RATE_G_PER_100KG": 200.0,
    "LABEL_SIGNAL_WORD": "WARNING",
    "TREATMENT_RATE_G_PER_100KG": 150.0,
}

# Golden-chain derived figures for the single-lot reference contract.
GOLDEN_FIGURES = {
    "MOISTURE_DOCKAGE_PCT": 3.75,
    "PROVISIONAL_CLEAN_KG": 36305.500,
    "PROVISIONAL_CLEAN_UNITS": 1452.22,
    "FINAL_CLEAN_UNITS": 1380.05,
    "BAG_COUNT": 1380,
    "ADJUSTED_PRICE_PER_UNIT_CENTS": 1929,
    "GERMINATION_VALID_UNTIL": "2027-06-11T00:00:00Z",
    "GROSS_PAYABLE_CENTS": 2662116,
    "CONDITIONING_CHARGES_CENTS": 303611,
    "PROVISIONAL_NET_CENTS": 2358505,
    "RECOVERY_CAP_PCT": 60.0,
    "ADVANCE_RECOVERY_CENTS": 1200000,
    "NET_PAYABLE_CENTS": 1158505,
}
