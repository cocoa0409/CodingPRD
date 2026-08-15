"""Domain thresholds — numeric constants from PRD calculation rules (sections 3.3-3.9)."""

# Advance rates in basis points (PRD section 3.3).
ADVANCE_RATE_BP_CHATTEL_CROP = 7500
ADVANCE_RATE_BP_EQUIPMENT = 7000
ADVANCE_RATE_BP_REAL_ESTATE = 8000
CROP_ADVANCE_BP = 6000

# Interest convention: basis points over ten thousand over a 360-day year (PRD 3.6).
DAY_COUNT_DENOMINATOR = 360
RATE_DIVISOR = 3_600_000  # 10_000 * 360

# Working-capital covenant tiers (PRD section 3.7).
TIER1_CAP_CENTS = 25_000_000
TIER2_CAP_CENTS = 100_000_000
TIER1_MILLI = 1100
TIER2_MILLI = 1250
TIER3_MILLI = 1400
RATIO_ZERO_ZERO = 0
RATIO_ZERO_LIABILITIES_POSITIVE_ASSETS = 999_999_999

# Patronage cap: a dividend never exceeds 25% of interest paid (PRD section 3.9).
PATRONAGE_CAP_BP = 2500

# Deferral minimum gap in days (PRD section 3.8).
DEFERRAL_MIN_GAP_DAYS = 30

# UCC continuation window: 180 days before lapse (PRD section 3.4).
UCC_CONTINUATION_WINDOW_DAYS = 180
UCC_FILING_TERM_YEARS = 5

# Coverage-band posture: one-tenth of the approved commitment (PRD section 3.8).
COVERAGE_WATCH_BAND_DIVISOR = 10

# Consecutive delinquent reviews that force DEFAULT (PRD section 2.4).
DEFAULT_DELINQUENT_REVIEW_THRESHOLD = 2

# Logical clock startup default (PRD section 2.4).
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "ASSOCIATION_NAME": "Blackhawk FCS",
    "CHARTER_NUMBER": "CH-1850",
    "LEGAL_NAME": "Sunrise Farms LLC",
    "TAX_ID": "41-0000001",
    "COUNTY": "BLACKHAWK",
    "COMMITMENT_CENTS": 50_000_000,
    "RATE_BPS": 700,
    "SEASON_YEAR": 2026,
    "MATURITY_DATE": "2027-02-28T00:00:00Z",
    "CROP_TYPE": "CORN",
    "JURISDICTION": "STATE_UCC_OFFICE",
    "COVERAGE_AMOUNT_CENTS": 40_000_000,
    "COVERAGE_START": "2026-03-01T00:00:00Z",
    "COVERAGE_END": "2027-03-01T00:00:00Z",
}
