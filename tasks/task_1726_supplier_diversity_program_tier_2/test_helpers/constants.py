"""Domain thresholds — numeric constants from PRD calculation rules."""

# Logical clock startup default (PRD: the clock starts at exactly this instant
# and must not fall back to wall-clock time before the first explicit set).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

# Supplier risk score weights (PRD supplier risk scores section).
RISK_FAILED_AUDIT_POINTS = 40
RISK_EXPIRED_UNRENEWED_POINTS = 10
RISK_OPEN_AUDIT_POINTS = 15
RISK_INFO_REQUESTED_POINTS = 5
RISK_SCORE_CAP = 100

# Scorecard attainment rating bands (PRD goals/scorecards section).
RATING_EXCEEDS_BAND = 110.00
RATING_MEETS_BAND = 100.00
RATING_NEAR_BAND = 80.00
ATTAINMENT_CAP = 999.99

# Audit cooling-off window after a FAILED audit outcome (PRD certification
# submission section).
SELF_CERT_COOLING_OFF_DAYS = 90

# Development engagement post-end buffer (PRD development engagements section).
ENGAGEMENT_BUFFER_DAYS = 30

# Inclusive calendar quarter ranges (PRD scorecard attribution section).
QUARTER_RANGES = {
    "Q1": ("01-01", "03-31"),
    "Q2": ("04-01", "06-30"),
    "Q3": ("07-01", "09-30"),
    "Q4": ("10-01", "12-31"),
}

# Certifying-body defaults per certification type (PRD: SELF_CERT uses the
# literal string 'SELF').
CERTIFYING_BODY = {
    "MBE": "NMSDC",
    "WBE": "WBENC",
    "VET": "NVBDC",
    "SDVET": "VA",
    "LGBTQBE": "NGLCC",
    "DOBE": "USBLN",
    "SBA8A": "SBA",
    "SELF_CERT": "SELF",
}

TEST_DEFAULTS = {
    "BU_NAME": "Aerospace",
    "BU_CODE": "AERO",
    "BU_LEAD": "lead-1",
    "VALID_FROM": "2026-01-01",
    "VALID_TO": "2026-12-31",
    "PERIOD": "2026-Q1",
    "ESTIMATED_VALUE_CENTS": 100000,
}
