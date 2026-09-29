"""Domain thresholds and numeric constants stated in the PRD."""

# PRD 2.4 — the logical clock before any client has set it.
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# PRD 3.4 — geocoding
GEOCODE_CONFIDENCE_FLOOR = 0.60
GEOCODE_BUFFER_FT = {
    "ROOFTOP": 0.0,
    "PARCEL_CENTROID": 25.0,
    "ZIP_CENTROID": 250.0,
    "FAILED": 0.0,
}

# PRD 3.8 — vertical datum shift from NGVD29 to NAVD88, keyed on state_code
DATUM_OFFSET_FT = {
    "CA": -2.44,
    "FL": -1.15,
    "TX": -0.87,
    "NC": -0.55,
}

# PRD 3.6 — statutory coverage caps in integer cents
REGULAR_CAP_CENTS = {
    "SINGLE_FAMILY": 25_000_000,
    "TWO_TO_FOUR_FAMILY": 25_000_000,
    "OTHER_RESIDENTIAL": 50_000_000,
    "NON_RESIDENTIAL": 50_000_000,
}
EMERGENCY_CAP_CENTS = {
    "SINGLE_FAMILY": 3_500_000,
    "TWO_TO_FOUR_FAMILY": 3_500_000,
    "OTHER_RESIDENTIAL": 10_000_000,
    "NON_RESIDENTIAL": 10_000_000,
}

# PRD 3.6 — notice response windows, in days
NOTICE_RESPONSE_DAYS = {
    "MANDATORY_PURCHASE": 45,
    "FORCE_PLACEMENT_WARNING": 30,
    "RE_DETERMINATION": 30,
    "COVERAGE_UNAVAILABLE": 15,
}
NOTICE_COOLDOWN_DAYS = 5

# PRD 3.2 — panel timeline windows, in days
APPEAL_PERIOD_DAYS = 90
LFD_WAITING_PERIOD_DAYS = 180

# PRD 3.9 — dispute windows
DISPUTE_DECISION_DAYS = 30
DISPUTE_MAX_ROUNDS = 2

# PRD 3.8 — certificate currency and the amendment fee schedule
CERTIFICATE_VALIDITY_DAYS = 365
BASE_FEE_CENTS = {"LOMA": 0, "LOMR_F": 50_000}
RESUBMISSION_FEE_CENTS = 12_500
EXPEDITE_SURCHARGE_PCT = {"TIER_1": 0.00, "TIER_2": 0.30, "TIER_3": 0.45}
RESUBMISSION_CEILING = 2

# PRD 3.6 — premium proration denominators
PREMIUM_DAYS_PER_YEAR = 365
PREMIUM_MONTHS_PER_YEAR = 12

TEST_DEFAULTS = {
    "ANNUAL_PREMIUM_RATE_CENTS": 288_000,
    "PRINCIPAL_BALANCE_CENTS": 28_000_000,
    "REPLACEMENT_COST_CENTS": 32_000_000,
    "ESCROW_BALANCE_CENTS": 500_000,
    "PANEL_BFE_FT": 7.75,
    "INSIDE_OFFSET_FT": -12.0,
    "OUTSIDE_OFFSET_FT": 30.0,
}
