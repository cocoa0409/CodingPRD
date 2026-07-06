"""Domain thresholds — numeric constants from the PRD's scoring, pricing, SLA, and credit rules."""

# Conformance scoring weights (PRD §2.6).
CONFORMANCE_WEIGHTS = {
    "CRITICAL": 10,
    "SERIOUS": 5,
    "MODERATE": 2,
    "MINOR": 1,
}

# Risk-exposure weights and factors (PRD §3.7).
RISK = {
    "CRIT_WEIGHT": 8,
    "SERIOUS_WEIGHT": 3,
    "OVERDUE_PER_DAY": 0.02,
    "OVERDUE_CAP": 1.0,
    "LEGAL_BUMP": 25,
    "SCORE_CAP": 100,
}

# Subscription invoice tier fees and per-page charges in cents (PRD §3.1).
TIER_FEE_CENTS = {
    "SCAN": 9900,
    "MONITOR": 24900,
    "MANAGED": 49900,
}
PER_PAGE_CENTS = {
    "SCAN": 0,
    "MONITOR": 5,
    "MANAGED": 12,
}
DISCOUNT_5_SITES = 0.10
DISCOUNT_10_SITES = 0.15

# Remediation SLA hours by severity (PRD §3.2).
SLA_HOURS = {
    "CRITICAL": 72,
    "SERIOUS": 168,
    "MODERATE": 720,
    "MINOR": 2160,
}

# Conformance level tier lower-bounds, inclusive (PRD §3.4).
CONFORMANCE_TIER_FULL_MIN = 95
CONFORMANCE_TIER_PARTIAL_MIN = 80
CONFORMANCE_TIER_A_MIN = 50

# Remediation credit in cents by conformance level (PRD §3.4).
CREDIT_CENTS = {
    "WCAG_AA_FULL": 0,
    "WCAG_AA_PARTIAL": 2500,
    "WCAG_A": 5000,
    "NON_CONFORMANT": 10000,
}

# Training pass threshold (PRD §3.8).
TRAINING_PASS_THRESHOLD = 80

# Certification validity window (PRD §3.5).
CERTIFICATION_VALID_DAYS = 365

# Logical-clock startup default (PRD §2.9).
CLOCK_DEFAULT = "2026-03-01T00:00:00Z"

TEST_DEFAULTS = {
    "LEGAL_NAME": "Test Org",
    "CONTACT_EMAIL": "contact@test.test",
    "WCAG_LEVEL": "AA",
    "PAGE_COUNT": 10,
    "EFFORT_HOURS": 2,
    "VENDOR_ID": "vendor-1",
}
