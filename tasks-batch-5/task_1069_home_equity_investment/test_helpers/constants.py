"""Domain thresholds — numeric constants from the PRD calculations (Section 3)."""

# Underwriting ceiling (PRD Section 3.3): combined_ltv <= 0.75.
MAX_COMBINED_LTV = 0.75

# risk_band thresholds (PRD Section 3.3).
RISK_BAND_LOW_MAX = 0.50
RISK_BAND_MODERATE_MAX = 0.65

# Offer investment cap (PRD Section 3.4): 30% of basis valued_amount, floored.
INVESTMENT_LTV_CAP = 0.30

# Settlement fee components (PRD Section 3.7).
ORIGINATION_FEE_PCT = 0.03
SERVICING_FEE_PCT = 0.01
ADMIN_FLAT_CENTS = 50000

# Elapsed-term divisor (PRD Section 3.7).
MONTHS_PER_YEAR = 12

# Scheduling buffer (PRD Section 3.2): appraiser double-booking window.
APPRAISER_BUFFER_MINUTES = 60

# Default logical-clock instant before any set call (PRD Section 2.9).
DEFAULT_CLOCK = "2026-07-01T00:00:00Z"

# Common test values reused across fixtures.
TEST_DEFAULTS = {
    "FUND_TOTAL_CENTS": 50000000,
    "AVM_VALUED_CENTS": 80000000,
    "REQUESTED_INVESTMENT_CENTS": 10000000,
    "EXISTING_MORTGAGE_CENTS": 40000000,
    "OPTION_PERCENTAGE": 0.25,
    "RISK_ADJUSTMENT_PCT": 0.10,
    "TERM_MONTHS": 120,
    "CAPPED_ANNUAL_RATE": 0.19,
    "OFFER_EXPIRES_AT": "2027-01-01T00:00:00Z",
}
