"""Domain thresholds — numeric constants from the PRD's catch-up rules."""

# The CDC four-day grace window (PRD §2.7), applied identically to both the
# minimum-age and minimum-interval thresholds; product grace_period_days
# defaults to this.
DEFAULT_GRACE_DAYS = 4

# Standard DTAP-like product parameters used across catch-up / interval tests.
DTAP_PRODUCT = {
    "product_code": "DTAP",
    "antigen": "DTAP",
    "doses_in_series": 5,
    "min_age_days": 42,
    "recommended_age_days": 60,
    "min_interval_days": 28,
    "grace_period_days": 4,
}

# Single-dose product needing one dose, no age/interval floor — for compliance
# and cascade scenarios where dose validity is trivially satisfied.
SINGLE_DOSE_PRODUCT = {
    "product_code": "C1",
    "antigen": "C1",
    "doses_in_series": 1,
    "min_age_days": 0,
    "recommended_age_days": 0,
    "min_interval_days": 0,
}

# Default test clock instant used by most catch-up fixtures.
DEFAULT_CLOCK = "2026-06-01T00:00:00Z"
