"""Domain thresholds — numeric constants from PRD calculations and §3."""

# Revocation deadline windows (PRD §3.4).
CALENDAR_WINDOW_DAYS = 10
BUSINESS_WINDOW_DAYS = 5

# Home study validity window (PRD §3.2).
VALIDITY_DAYS = 365

# Consent eligibility (PRD §3.4).
MIN_HOURS_AFTER_BIRTH = 72

# Required post-placement visit counts (PRD §3.6).
REQUIRED_VISITS_INSTATE = 3
REQUIRED_VISITS_INTERSTATE = 6

# Counseling buffer (PRD §3.3).
COUNSELING_BUFFER_MINUTES = 60

# Agency fee sliding-scale bands and cap (PRD §3.8).
LOW_BAND_CENTS = 4_000_000      # $40,000.00
HIGH_BAND_CENTS = 12_000_000    # $120,000.00
REIMBURSABLE_CAP_CENTS = 1_500_000  # $15,000.00

# Sliding-scale fractions (PRD §3.8).
LOW_BAND_PCT = -0.20
MID_BAND_PCT = 0.00
HIGH_BAND_PCT = 0.15

# Common test defaults.
TEST_DEFAULTS = {
    "FEE_SCHEDULE_CENTS": 3_000_000,
    "MID_BAND_INCOME_CENTS": 8_000_000,
    "HIGH_BAND_INCOME_CENTS": 15_000_000,
    "LOW_BAND_INCOME_CENTS": 3_000_000,
    "CLOCK_BASE": "2026-06-04T08:00:00.000Z",
    "CHILD_DOB": "2026-06-01T08:00:00.000Z",
}
