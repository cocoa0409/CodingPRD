"""Domain thresholds and numeric constants stated by the PRD."""

# The logical clock's fixed starting instant (PRD §2.4) and its rendered form.
DEFAULT_CLOCK = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_RENDERED = "2026-08-01T00:00:00.000Z"
DEFAULT_CLOCK_DATE = "2026-08-01"

# Coverage arithmetic (PRD §3.4).
COVERAGE_WEIGHTS = {
    "SCREEN_READER": 0.45,
    "KEYBOARD": 0.35,
    "MAGNIFICATION": 0.20,
}
AUTOMATED_CREDIT_PER_CRITERION = 0.4
AUTOMATED_ONLY_PROFILE_CAP = 0.60
MANUAL_PROFILE_CAP = 1.00

# Conformance index support weights (PRD §3.6).
SUPPORT_WEIGHT = {
    "SUPPORTS": 1.0,
    "PARTIALLY_SUPPORTS": 0.5,
    "DOES_NOT_SUPPORT": 0.0,
}

# Known-issue risk scoring (PRD §3.9).
RISK_SEVERITY_POINTS = {
    "BLOCKER": 40,
    "SERIOUS": 25,
    "MODERATE": 12,
    "MINOR": 5,
}

# Questionnaire disclosure debt base points (PRD §3.10).
DEBT_SEVERITY_POINTS = {
    "BLOCKER": 8,
    "SERIOUS": 5,
    "MODERATE": 3,
    "MINOR": 1,
}

# Disclosure-debt staleness penalty rate per bucket, by tier (PRD §3.10).
TIER_PENALTY_RATE = {
    "STANDARD": 0.5,
    "ELEVATED": 1.0,
    "CRITICAL": 2.0,
}

THRESHOLDS = {
    # Attestation floor and coverage (PRD §3.4)
    "ATTESTATION_FLOOR": 45.00,
    "AUTOMATED_ONLY_CEILING": 60.00,
    # Assessment evidence freshness (PRD §3.5)
    "EVIDENCE_FRESHNESS_DAYS": 90,
    # Publication posture (PRD §3.8)
    "POSTURE_INDEX_FLOOR": 85.00,
    "POSTURE_STALE_QUESTIONNAIRE_LIMIT": 2,
    "RESTRICTED_UPDATE_DUE_DAYS": 30,
    "FROZEN_CORRECTION_DUE_DAYS": 10,
    # Bench scheduling (PRD §3.3)
    "DEFAULT_RECONFIGURATION_BUFFER_MINUTES": 30,
    "MAX_RECONFIGURATION_BUFFER_MINUTES": 240,
    # Risk scoring (PRD §3.9)
    "BREADTH_STEP_PER_EXTRA_CATEGORY": 0.15,
    "REACH_BASE": 0.5,
    "REACH_SLOPE": 0.5,
    "AGING_STEP_PER_DAY": 0.02,
    "AGING_MAX_DAYS": 60,
    "COMPLAINT_STEP": 0.1,
    "COMPLAINT_CAP": 5,
    "RISK_SCORE_CLAMP": 100.00,
    # Remediation budget waterfall (PRD §3.9)
    "REMEDIATION_RATE_CENTS_PER_POINT": 18750,
    "PROGRAMME_OVERHEAD_FACTOR": 1.0725,
    # Questionnaire cadence and disclosure debt (PRD §3.10)
    "UPDATE_CADENCE_DAYS": 90,
    "DEBT_OVERDUE_SURCHARGE": 2,
    "DEBT_TIER_STANDARD_MAX": 6,
    "DEBT_TIER_ELEVATED_MAX": 12,
    "DEBT_STALENESS_BUCKET_DAYS": 30,
    "DEBT_STALENESS_BUCKET_CAP": 4,
    # Report withdrawal cascade (PRD §3.7)
    "WITHDRAWAL_CORRECTION_DUE_DAYS": 10,
    # Pagination (PRD §2.3)
    "PAGINATION_DEFAULT_LIMIT": 10,
    "PAGINATION_MIN_LIMIT": 1,
    "PAGINATION_MAX_LIMIT": 100,
}

TEST_DEFAULTS = {
    "STANDARD_CODE": "WCAG_2_1",
    "STANDARD_TITLE": "Web Content Accessibility Guidelines 2.1",
    "SURFACE_SCOPE": "BOTH",
    "MAX_TARGET_LEVEL": "AA",
    "CRITERION_NUMBER": "1.4.3",
    "CRITERION_TITLE": "Contrast (Minimum)",
    "PRODUCT_NAME": "Atlas Portal",
    "VERSION_LABEL": "2026.8",
    "TARGET_LEVEL": "AA",
    "SURFACE_TYPE": "WEB",
    "COMPONENT_NAME": "Checkout Flow",
    "COMPONENT_TYPE": "WEB_UI",
    "APPLICABLE_CRITERIA_COUNT": 100,
    "USER_REACH_PCT": 80,
    "ENVIRONMENT_NAME": "NVDA Bench 1",
    "AT_PRODUCT_NAME": "NVDA 2026.1",
    "OS_PLATFORM": "WINDOWS",
    "REPORT_TITLE": "Atlas Portal Accessibility Conformance Report",
    "TRAIN_NAME": "2026.09",
    "CUSTOMER_NAME": "State Procurement Office",
    "QUESTIONNAIRE_KIND": "VPAT_ACR",
    "ANSWERS_SUMMARY": "Atlas Portal conforms to WCAG 2.1 level AA with the exceptions listed.",
    "COMPLAINT_CHANNEL": "WEB_FORM",
    "COMPLAINT_DESCRIPTION": "Screen reader announces the checkout total incorrectly.",
    "ISSUE_SUMMARY": "Checkout total is not announced by screen readers on the review step.",
}

# Syntactically valid UUIDs that address nothing.
UNKNOWN_UUIDS = {
    "standard": "11111111-1111-4111-8111-111111111101",
    "criterion": "11111111-1111-4111-8111-111111111102",
    "product": "11111111-1111-4111-8111-111111111103",
    "component": "11111111-1111-4111-8111-111111111104",
    "environment": "11111111-1111-4111-8111-111111111105",
    "run": "11111111-1111-4111-8111-111111111106",
    "assessment": "11111111-1111-4111-8111-111111111107",
    "report": "11111111-1111-4111-8111-111111111108",
    "release_train": "11111111-1111-4111-8111-111111111109",
    "known_issue": "11111111-1111-4111-8111-111111111110",
    "questionnaire": "11111111-1111-4111-8111-111111111111",
    "complaint": "11111111-1111-4111-8111-111111111112",
}
