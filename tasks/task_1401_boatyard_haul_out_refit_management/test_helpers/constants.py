"""Domain thresholds — numeric constants from the PRD's calculation rules."""

# Lift and insurance gates (PRD section 3.3 / 3.1)
LIFT_CAPACITY_TONS = 60
LIFT_BUFFER_MINUTES = 30
INSURANCE_MIN_LIABILITY_CENTS = 100000000

# Environmental runoff thresholds (PRD section 3.8)
VIOLATION_PPM = 100.0
ADVISORY_PPM = 50.0

# Storage accrual — DAILY variant tier rates and winter multiplier
# (PRD section 3.11)
TIER1_CENTS_PER_FT = 50
TIER1_MAX_DAY = 7
TIER2_CENTS_PER_FT = 65
TIER2_MAX_DAY = 30
TIER3_CENTS_PER_FT = 85
WINTER_MULTIPLIER = 0.85

# Storage accrual — MONTHLY_CONTRACT variant (PRD section 3.11)
MONTHLY_BLOCK_CENTS_PER_FT = 1400
MONTHLY_BLOCK_DAYS = 30

# Labor and fiscal rules (PRD sections 3.6, 3.7, 3.10)
SUBCONTRACTOR_MARKUP = 1.15
OWNER_SUPPLIED_HANDLING_PCT = 0.10
DEPOSIT_PCT = 0.25

# The logical clock's startup value (PRD section 2.6)
LOGICAL_CLOCK_START = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "LOA_FT": 40,
    "BEAM_FT": 13,
    "DISPLACEMENT_TONS": 20,
    "CERT_COVERAGE_CENTS": 200000000,
    "CERT_EFFECTIVE_DATE": "2026-01-01",
    "CERT_EXPIRY_DATE": "2027-06-01",
    "HAUL_DATE": "2026-08-02",
    "SPLASH_DATE": "2026-08-20",
    "OWNER_USER_ID": "owner-1",
}
