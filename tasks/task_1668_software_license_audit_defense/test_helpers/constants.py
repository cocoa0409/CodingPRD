"""Domain thresholds — numeric constants named in the PRD (§2.4, §3.4, §3.7, §3.9)."""

# Logical clock startup default (PRD §2.4): "its value at server startup is
# exactly 2026-08-01T00:00:00Z".
CLOCK_DEFAULT_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # Severity ladder (PRD §3.4)
    "GRACE_RATIO": 1.05,
    "MATERIAL_RATIO": 1.25,
    "MATERIAL_QTY": 10,
    "CRITICAL_QTY": 100,
    "MISSION_CRITICAL_QTY": 25,
    # Vendor finding back-support years (PRD §3.7)
    "BACK_SUPPORT_YEARS": 2,
    # Entitlement-expiry warning window in days (PRD §3.9)
    "EXPIRY_WARNING_DAYS": 30,
    # Vendor default response deadline in days (PRD §3.1)
    "DEFAULT_NOTICE_RESPONSE_DEADLINE_DAYS": 30,
    # Future-license discount ceiling on offers (PRD §3.7)
    "MAX_FUTURE_LICENSE_DISCOUNT_PCT": 0.5,
}

TEST_DEFAULTS = {
    "UNIT_LIST_PRICE_CENTS": 10000,
    "SUPPORT_RATE_PCT": 0.22,
}
