"""Domain thresholds and shared temporal constants (PRD §2.4, §2.9, §3)."""

# Basis-point arithmetic (PRD §2.9): percentages scaled by ten thousand, round half up.
BP_SCALE = 10000
# Contested meetings: effective quorum threshold never below one half (PRD §3.7).
CONTESTED_MIN_QUORUM_PCT = 0.50
# Share-class vote weights (PRD §2.9).
CLASS_WEIGHT_COMMON = 1.0
CLASS_WEIGHT_PREFERRED = 0.5
# Same-party solicitation windows must be separated by at least 24 hours (PRD §3.6).
CAMPAIGN_MIN_GAP_HOURS = 24

# Logical clock startup default (PRD §2.4).
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

# Standard temporal coordinates used across fixtures.
RECORD_DATE = "2026-08-10"
MEETING_DATETIME = "2026-09-15T16:00:00Z"

TEST_DEFAULTS = {
    "COMPANY_NAME": "Acme Corp",
    "TICKER": "ACME",
    "MEETING_TYPE": "ANNUAL",
    "MEETING_MODE": "VIRTUAL",
    "QUORUM_THRESHOLD_PCT": 0.5,
    "OUTSTANDING_SHARES": 10000,
    "SHARES_HELD": 6000,
}
