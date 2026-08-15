"""Domain thresholds — numeric constants from the PRD's calculations (§2.4, §3)."""

THRESHOLDS = {
    # Each subrecipient commitment's MTDC-eligible subaward allowance (PRD §3.3)
    "SUBAWARD_MTDC_ALLOWANCE_CENTS": 2_500_000,
    # Subrecipient risk scoring (PRD §3.7)
    "FINDINGS_CAP": 25,
    "FINDINGS_STEP": 5,
    "FOREIGN_PENALTY": 10,
    "FIRST_TIME_PENALTY": 10,
    "ENHANCED_AMOUNT_THRESHOLD_CENTS": 25_000_000,
    "ENHANCED_SURCHARGE": 15,
    "TIER_LOW_MAX": 24,
    "TIER_MEDIUM_MAX": 49,
    # PI effort capacity ceiling (PRD §3.5)
    "MAX_EFFORT_PCT": 100.00,
    # Internal routing lead time default in days (PRD §3.1)
    "DEFAULT_INTERNAL_LEAD_DAYS": 5,
    # JIT response window default in days (PRD §3.8)
    "DEFAULT_JIT_DUE_IN_DAYS": 14,
    # Cost-share adequacy third-party credit terms (PRD §3.4)
    "THIRD_PARTY_CREDIT_FACTOR": 0.5,
    "THIRD_PARTY_CAP_OF_REQUIRED": 0.25,
}

# Default validity windows (days) applied at review approval (PRD §3.6)
REVIEW_VALIDITY_DAYS = {
    "IRB": 365,
    "IACUC": 1095,
    "EXPORT_CONTROL": 730,
    "CONFLICT_OF_INTEREST": 365,
}

# Risk-score base points by single_audit_status (PRD §3.7)
AUDIT_STATUS_BASE_POINTS = {
    "CURRENT": 10,
    "NOT_REQUIRED": 20,
    "MISSING": 45,
    "DELINQUENT": 60,
}

# The logical clock reads exactly this instant before any admin call (PRD §2.4)
DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

TEST_DEFAULTS = {
    "RATE_PCT": 54.00,
    "SPONSOR_DEADLINE_AT": "2026-09-05T17:00:00Z",
    "RATE_WINDOW_START": "2026-01-01",
    "RATE_WINDOW_END": "2029-01-01",
    "PROJECT_START_ON": "2026-09-01",
    "PROJECT_END_ON": "2027-08-31",
    "LINE_AMOUNT_CENTS": 10_000_000,
}
