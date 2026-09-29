"""Domain thresholds and shared test fixtures data drawn from the PRD narrative."""

# --------------------------------------------------------------------------
# Numeric constants named by the PRD business rules
# --------------------------------------------------------------------------
THRESHOLDS = {
    # Blend arithmetic
    "VISCOSITY_OFFSET": 0.7,
    "BLEND_DENSITY_KG_PER_L": 0.860,
    # Heel chemistry ceilings
    "MAX_HEEL_RATIO_CROSS_FAMILY": 0.005000,
    "MAX_HEEL_RATIO_SAME_FAMILY": 0.020000,
    "CLAIM_HEEL_LIMIT_CROSS_FAMILY": 0.001000,
    "CLAIM_HEEL_LIMIT_SAME_FAMILY": 0.010000,
    # Vessel handover
    "HEEL_RETENTION_PCT": 0.5,
    # Quality
    "MIN_RETAIN_COUNT": 2,
    "REQUIRED_TESTS": ["KV100", "TBN"],
    "RETENTION_DAYS_STANDARD": 365,
    "RETENTION_DAYS_CLAIM_BEARING": 1095,
    "CLAIM_VALIDITY_DAYS": 730,
    # Occupancy geometry
    "CHANGEOVER_BUFFER_MINUTES": 120,
    # Take-back
    "MAX_CONTAMINATION_PCT": 25,
    "TAKEBACK_FLAT_RATE_CENTS_PER_L": 18,
    "TAKEBACK_BASE_RATE_CENTS_PER_L": 25,
    "TAKEBACK_CREDIT_CAP_PCT": 15,
    # Freight
    "BULK_FREE_FREIGHT_L": 4000,
    "BULK_MIN_FREIGHT_CENTS": 48000,
    "PACKAGED_FREIGHT_FREE_THRESHOLD_CENTS": 1000000,
    "PACKAGED_FREIGHT_MID_THRESHOLD_CENTS": 500000,
    "PACKAGED_FREIGHT_MID_CENTS": 22500,
    "PACKAGED_FREIGHT_LOW_CENTS": 39500,
}

PACKAGE_RATE_CENTS_PER_L = {
    "BULK": 320,
    "IBC_1000L": 380,
    "DRUM_205L": 425,
    "PAIL_20L": 505,
    "CASE_12X1L": 640,
}

TIER_DISCOUNT_PCT = {"TIER_A": 12.0, "TIER_B": 7.5, "TIER_C": 0.0}

PRIVATE_LABEL_UPLIFT_PCT = 4.5


# --------------------------------------------------------------------------
# Logical-clock instants used across the suite
# --------------------------------------------------------------------------
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00.000Z"
CLOCK_BASE = "2026-08-02T06:00:00Z"
CLOCK_BASE_ISO = "2026-08-02T06:00:00.000Z"

WINDOW_A_START = "2026-08-02T08:00:00Z"
WINDOW_A_END = "2026-08-02T12:00:00Z"
WINDOW_B_START = "2026-08-02T12:00:00Z"
WINDOW_B_END = "2026-08-02T16:00:00Z"
WINDOW_C_START = "2026-08-02T14:00:00Z"
WINDOW_C_END = "2026-08-02T18:00:00Z"

# The four canonical material lots are booked in on separate days so that their
# `created_at` stamps genuinely differ. PRD 3.3 orders draw candidates by
# `created_at` ascending and only falls back to `received_kg` descending on a
# tie, so the small cheap base-oil lot must be strictly older than the large
# expensive one for a draw to span two layers.
LOT_RECEIPT_INSTANTS = [
    "2026-08-01T02:00:00Z",
    "2026-08-01T03:00:00Z",
    "2026-08-01T04:00:00Z",
    "2026-08-01T05:00:00Z",
]

RUN_WINDOW_START = "2026-08-03T10:00:00Z"
RUN_WINDOW_END = "2026-08-03T12:00:00Z"


# --------------------------------------------------------------------------
# Operator identifiers. The laboratory identifiers are stamped onto every
# result, so a disposition caller must use a different identifier.
# --------------------------------------------------------------------------
QC_TECH_ID = "qc-101"
QC_TECH_ALT_ID = "qc-102"
QUALITY_MANAGER_ID = "qm-201"


# --------------------------------------------------------------------------
# Canonical material and product data used by the composite setups
# --------------------------------------------------------------------------
STANDARD_COMPONENTS = [
    {
        "component_code": "GRP2-150N",
        "component_type": "BASE_OIL",
        "mass_fraction_pct": 84.00,
        "nominal_kv100_cst": 5.200,
        "additive_family": "NONE",
    },
    {
        "component_code": "OCP-VII",
        "component_type": "VI_IMPROVER",
        "mass_fraction_pct": 6.00,
        "nominal_kv100_cst": 850.000,
        "additive_family": "NONE",
    },
    {
        "component_code": "ADD-SN-PLUS",
        "component_type": "ADDITIVE_PACKAGE",
        "mass_fraction_pct": 10.00,
        "nominal_kv100_cst": 105.000,
        "additive_family": "ZDDP_PCMO",
    },
]

# The standard three-material formulation predicts 7.614 cSt at 100 C.
STANDARD_PREDICTED_KV100 = 7.614
STANDARD_ADDITIVE_TREAT_PCT = 10.00

TEST_DEFAULTS = {
    "SPEC_PRODUCT_CODE": "LUBE-0W20-SP",
    "SPEC_TARGET_KV100": 7.600,
    "SPEC_TOLERANCE_PCT": 3.0,
    "SPEC_MIN_TREAT_PCT": 8.00,
    "TANK_CODE": "TK-01",
    "TANK_CAPACITY_L": 5000.0,
    "TANK_HEEL_L": 10.0,
    "BATCH_CODE": "B-0001",
    "BATCH_PLANNED_VOLUME_L": 2000.0,
    "CHARGE_VOLUME_L": 1990.0,
    "LINE_CODE": "PL-1",
    "CREDIT_LIMIT_CENTS": 5000000,
}
