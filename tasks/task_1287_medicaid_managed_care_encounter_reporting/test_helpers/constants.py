"""Domain thresholds and constants from PRD calculations and configuration defaults."""

THRESHOLDS = {
    # Program creation defaults (PRD §3.1)
    "COMPLETENESS_THRESHOLD_DEFAULT": 0.98,
    "ACCURACY_THRESHOLD_DEFAULT": 0.95,
    "PROVIDER_YELLOW_THRESHOLD_DEFAULT": 0.02,
    "PROVIDER_RED_THRESHOLD_DEFAULT": 0.05,
    "PENALTY_CAP_PERCENT_DEFAULT": 0.10,
    # Calculation constants (PRD §3.8, §3.9)
    "ENCOUNTERS_PER_MEMBER_MONTH": 0.5,
    "RATE_PER_POINT_CENTS": 50000,
    "LATE_FLAT_CENTS": 500000,
    "LATE_PER_DAY_CENTS": 100000,
    "WITHHOLD_PERCENT": 0.05,
}

# HCC condition weights for risk scoring (PRD §3.9)
HCC_WEIGHTS = {
    "E11": 0.8,
    "I50": 1.2,
    "F32": 0.4,
    "J45": 0.3,
    "N18": 1.0,
}

TEST_DEFAULTS = {
    "STATE_CODE": "CA",
    "COMPANION_GUIDE_VERSION": "CG-2026.1",
    # A posture threshold so high that programs never flip RESTRICTED in ordinary fixtures
    "SAFE_PENALTY_THRESHOLD_CENTS": 100000000,
    "PMPM_TANF_CENTS": 50000,
    "PMPM_SSI_CENTS": 120000,
    "NPI": "1234567890",
    "TAXONOMY_CODE": "207Q00000X",
    "PLACE_OF_SERVICE": "11",
    "PROCEDURE_CODE": "99213",
    "PAID_AMOUNT_CENTS": 10000,
    # Standard August 2026 reporting cycle geometry used by most fixtures
    "CYCLE_LABEL": "2026-08",
    "WINDOW_START": "2026-08-01T00:00:00Z",
    "WINDOW_END": "2026-09-01T00:00:00Z",
    "SUBMISSION_DEADLINE": "2026-09-15T00:00:00Z",
    "RATE_EFFECTIVE_FROM": "2026-08-01",
    "RATE_EFFECTIVE_TO": "2026-08-31",
    "ENROLLED_FROM": "2026-08-01",
    # Logical clock fixed startup default (PRD §2.4)
    "CLOCK_DEFAULT": "2026-08-01T00:00:00Z",
    # User ids for segregation-of-duties-safe sealing/transmitting
    "OPS_SEALER_USER_ID": "ops-1",
    "COMPLIANCE_TRANSMITTER_USER_ID": "comp-1",
}

# Edit codes (PRD §3.4, §3.6)
EDIT_CODES = {
    "E101_SERVICE_DATE_ORDER": "E101_SERVICE_DATE_ORDER",
    "E102_DIAG_FORMAT": "E102_DIAG_FORMAT",
    "E201_MEMBER_NOT_ELIGIBLE": "E201_MEMBER_NOT_ELIGIBLE",
    "E202_PROVIDER_INACTIVE": "E202_PROVIDER_INACTIVE",
    "E301_DUPLICATE_SUSPECT": "E301_DUPLICATE_SUSPECT",
    "E302_UNITS_HIGH": "E302_UNITS_HIGH",
    "STATE_DENIAL": "E501_STATE_EDIT",
    "STATE_FILE_REJECT": "E599_FILE_REJECT",
}
