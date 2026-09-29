"""Domain thresholds and rate tables taken from the PRD's stated formulas."""

# --------------------------------------------------------------------------
# The logical conservation clock (PRD §2.6)
# --------------------------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# --------------------------------------------------------------------------
# Pagination (PRD §2.3)
# --------------------------------------------------------------------------
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

# --------------------------------------------------------------------------
# Condition index (PRD §3.2)
# --------------------------------------------------------------------------
MATERIAL_DEFECT_WEIGHTS = {
    "BRONZE": {
        "surface_score": 0.30,
        "structural_score": 0.25,
        "coating_score": 0.20,
        "mount_score": 0.15,
        "graffiti_score": 0.10,
    },
    "PAINTED_STEEL": {
        "surface_score": 0.20,
        "structural_score": 0.20,
        "coating_score": 0.35,
        "mount_score": 0.15,
        "graffiti_score": 0.10,
    },
    "STONE": {
        "surface_score": 0.25,
        "structural_score": 0.35,
        "coating_score": 0.05,
        "mount_score": 0.20,
        "graffiti_score": 0.15,
    },
    "MURAL_COATING": {
        "surface_score": 0.35,
        "structural_score": 0.10,
        "coating_score": 0.30,
        "mount_score": 0.05,
        "graffiti_score": 0.20,
    },
}

EXPOSURE_PENALTY = {"COASTAL": 6.0, "URBAN": 3.0, "PARK": 1.5, "INTERIOR": 0.0}
SEVERITY_FACTOR_MAX_SUBSCORE_4 = 1.0
SEVERITY_FACTOR_OTHERWISE = 0.5
DEFECT_MULTIPLIER = 25
INDEX_BASE = 100

TREATMENT_TRIGGER_INDEX = 55.0
RECOMMENDATION_BANDS = {
    "NONE": 75.0,      # index >= 75.0
    "ROUTINE": 55.0,   # 55.0 <= index < 75.0
    "PRIORITY": 30.0,  # 30.0 <= index < 55.0
    # URGENT: index < 30.0
}

MIN_PHOTOS_FOR_SUBMISSION = 3
MAX_REVISION_ROUNDS = 2

# --------------------------------------------------------------------------
# Graffiti response allowances in hours (PRD §3.3)
# --------------------------------------------------------------------------
GRAFFITI_SLA_HOURS = {
    "MURAL_COATING": 48,
    "PAINTED_STEEL": 72,
    "BRONZE": 120,
    "STONE": 120,
}

# --------------------------------------------------------------------------
# Treatment proposal estimate (PRD §3.4)
# --------------------------------------------------------------------------
COMPLEXITY_FACTORS = {
    "STABILIZATION": 1.00,
    "SURFACE": 1.15,
    "COATING": 1.25,
    "STRUCTURAL": 1.40,
    "GRAFFITI": 1.10,
}
OVERHEAD_RATE = 0.115
CONTINGENCY_RATE = 0.075
MOBILIZATION_CENTS = 45_000

# --------------------------------------------------------------------------
# Approval gates (PRD §3.5)
# --------------------------------------------------------------------------
CONSERVATOR_BUFFER_HOURS = 48

# --------------------------------------------------------------------------
# Treatment priority score (PRD §3.9)
# --------------------------------------------------------------------------
SIGNIFICANCE_FACTORS = {"LANDMARK": 1.5, "SIGNIFICANT": 1.2, "STANDARD": 1.0}
PRIORITY_EXPOSURE_FACTORS = {"COASTAL": 1.3, "URBAN": 1.25, "PARK": 1.1, "INTERIOR": 1.0}
DEFERRAL_PER_DAY = 0.004
DEFERRAL_CAP = 1.60

# --------------------------------------------------------------------------
# Deaccession balloting (PRD §3.8)
# --------------------------------------------------------------------------
QUORUM_MIN_VOTES = 5
APPROVAL_RATIO_THRESHOLD = 0.60
DEFAULT_COMMENT_DAYS = 45

# --------------------------------------------------------------------------
# Funding pools (PRD §3.10)
# --------------------------------------------------------------------------
SUPPLEMENT_TIER1_FLOOR_CENTS = 5_000_000
SUPPLEMENT_TIER2_FLOOR_CENTS = 20_000_000
SUPPLEMENT_TIER0_BPS = 0
SUPPLEMENT_TIER1_BPS = 75
SUPPLEMENT_TIER2_BPS = 125
ADMIN_FEE_RATE = 0.0225
BPS_DIVISOR = 10_000
MAX_DRAW_RATE_BPS = 2000

# --------------------------------------------------------------------------
# Insurance claims (PRD §3.11)
# --------------------------------------------------------------------------
POLICY_LIMIT_CENTS = 25_000_000
DEDUCTIBLE_CENTS = 250_000
ANNUAL_DEPRECIATION_FACTOR = 0.98
MAX_DEPRECIATION_AGE_YEARS = 25

# --------------------------------------------------------------------------
# Declared input defaults (PRD §3.1, §3.3, §3.8)
# --------------------------------------------------------------------------
DEFAULT_NOTICE_WAIT_DAYS = 90
DEFAULT_CONSULTATION_RESPONSE_DAYS = 30
DEFAULT_MAX_ANNUAL_APPLICATIONS = 4
DEFAULT_CONCURRENT_WORK_CAPACITY = 1

# --------------------------------------------------------------------------
# Canonical scenario values reused across the suite
# --------------------------------------------------------------------------
TEST_DEFAULTS = {
    "ARTIST_NAME": "Ada Vance",
    "ARTIST_EMAIL": "ada@example.gov",
    "SITE_CODE": "PLZ-1",
    "SITE_NAME": "Civic Plaza",
    "SITE_ADDRESS": "1 Civic Center",
    "ACCESSION_NUMBER": "2024.001",
    "ARTWORK_TITLE": "Standing Figure",
    "FOOTPRINT_UNITS": 6,
    "INSURED_VALUE_CENTS": 12_000_000,
    "ACQUISITION_DATE": "2014-06-01",
    "ACQUISITION_DOCUMENT_REF": "DEED-2014-001",
    "CONSERVATOR_FIRM": "Patina Studio",
    "CONSERVATOR_HOURLY_RATE_CENTS": 14_500,
    "CONSERVATOR_INSURANCE_EXPIRES_ON": "2027-01-31",
    "PROTOCOL_CODE": "WASH-BR",
    "PROTOCOL_CYCLE_DAYS": 180,
    "POOL_CODE": "END-2026",
    "POOL_PRINCIPAL_CENTS": 400_000_000,
    "POOL_DRAW_RATE_BPS": 450,
    # An ENDOWMENT pool of 400000000 cents at 450 bps: gross draw 18000000
    # selects the 75 bps supplemental tier (1500000 more, giving 21000000
    # before fees), the 2.25 percent administrative fee is 472500, so
    # draw_authorized_cents is 20527500.
    "POOL_ADMIN_FEE_CENTS": 472_500,
    "POOL_DRAW_AUTHORIZED_CENTS": 20_527_500,
    # Two cost lines of 12.5 hours at 14500 cents/hour: COATING (factor 1.25)
    # and SURFACE (factor 1.15) plus 82500 and 15000 cents of materials.
    "TWO_LINE_ESTIMATE_TOTAL_CENTS": 683_269,
    "TREATMENT_ALLOCATION_CENTS": 700_000,
    "MAINTENANCE_ALLOCATION_CENTS": 250_000,
}
