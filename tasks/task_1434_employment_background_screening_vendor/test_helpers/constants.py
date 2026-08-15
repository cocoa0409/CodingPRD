"""Domain thresholds and shared instants from PRD business rules."""

THRESHOLDS = {
    # FCRA baseline pre-adverse wait, in business days.
    "FCRA_BASE_WAIT_BUSINESS_DAYS": 5,
    # A vendor auto-transitions ACTIVE -> PROBATION at this many consecutive breaches.
    "BREACH_PROBATION_THRESHOLD": 3,
    # Audit failure threshold in basis points; strictly greater fails.
    "AUDIT_FAIL_THRESHOLD_BPS": 200,
    # SLA credit percentage subtracted from the provisional fee on a breached delivery.
    "SLA_CREDIT_PCT": 10,
    # Consent freshness window in calendar days after authorization_signed_at.
    "CONSENT_FRESHNESS_DAYS": 90,
    # Dispute filing window in calendar days after report delivery.
    "DISPUTE_WINDOW_DAYS": 30,
    # Perfect-accuracy basis points when the relevant audit set is empty.
    "PERFECT_ACCURACY_BPS": 10000,
}

# The fixed startup default of the logical clock.
CLOCK_STARTUP_DEFAULT = "2026-08-01T00:00:00Z"

# Business window bounds on each Monday-Friday UTC day.
BUSINESS_WINDOW_START_HOUR = 9
BUSINESS_WINDOW_END_HOUR = 17
BUSINESS_HOURS_PER_DAY = 8

TEST_DEFAULTS = {
    "VENDOR_BASE_TAT": 40,
    "VENDOR_MAX_CONCURRENT": 5,
    "PACKAGE_TAT": 40,
    "PACKAGE_FEE_CENTS": 10000,
    "POSITION_SALARY_CENTS": 9000000,
    "JURISDICTION_CODE": "US-CA",
    "RISK_TIER": "TIER_1_STANDARD",
}
