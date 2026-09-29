"""Domain thresholds and pinned numeric constants from the PRD calculations."""

THRESHOLDS = {
    # PRD §3.2 — statutory labor-rate ceiling
    "MAX_STEP_UP_PCT": 0.25,
    "TIME_AND_PRICE_STEP_PCT": 0.10,
    # PRD §3.4 — automated edit engine
    "HIGH_VALUE_THRESHOLD_CENTS": 150000,
    "NARRATIVE_THIN_CHARS": 20,
    "NARRATIVE_MIN_CHARS": 10,
    "OVERLAP_BUFFER_DAYS": 30,
    "REPEAT_REPAIR_WINDOW_DAYS": 180,
    # PRD §3.5 — goodwill authority
    "ADJUDICATOR_BASE_LIMIT_CENTS": 50000,
    "MANAGER_BASE_LIMIT_CENTS": 250000,
    "GOODWILL_DECAY_FACTOR": 2.0,
    "GOODWILL_MAX_SHARE": 0.80,
    # PRD §3.7 — failed-component analysis
    "NOT_AVAILABLE_SHARE": 0.50,
    # PRD §3.8 — extrapolation tiers
    "EXTRAPOLATION_FULL_TIER": 0.10,
    "EXTRAPOLATION_HALF_TIER": 0.05,
    # PRD §3.9 — expense analytics
    "ANALYTICS_WINDOW_DAYS": 365,
    "OUTLIER_RATIO_THRESHOLD": 1.50,
    # PRD §2.8 — dealer posture bands
    "PROBATION_THRESHOLD_CENTS": 90000,
    "SUSPENSION_THRESHOLD_CENTS": 200000,
}

# PRD §2.6 — the logical clock before it has ever been set.
DEFAULT_CLOCK_INSTANT = "2026-08-01T00:00:00Z"

# PRD §2.3 — pagination bounds.
PAGINATION = {
    "DEFAULT_LIMIT": 10,
    "MIN_LIMIT": 1,
    "MAX_LIMIT": 100,
    "DEFAULT_OFFSET": 0,
}

TEST_DEFAULTS = {
    # Reference data used by the shared claim worlds.
    "MARKUP_CAP_PCT": 0.30,
    "MAX_LABOR_RATE_CENTS": 20000,
    "MIN_SAMPLE_REPAIR_ORDERS": 5,
    "DEEMED_APPROVED_DAYS": 60,
    "APPEAL_WINDOW_DAYS": 30,
    "DEALER_LABOR_RATE_CENTS": 8250,
    "DEALER_MARKUP_PCT": 0.40,
    "VEHICLES_IN_OPERATION": 200,
    "PART_DEALER_NET_CENTS": 24799,
    "STANDARD_TIME_HOURS": 2.5,
    "MAX_TIME_HOURS": 3.5,
    "RETENTION_DAYS": 30,
}

# Opaque operator identifiers (PRD §2.1): manufacturer-side X-User-ID values are
# not tied to any persisted entity.
OPERATORS = {
    "WARRANTY_ADMIN": "wa-user-1",
    "ADJUDICATOR": "adj-user-1",
    "ADJUDICATOR_ALT": "adj-user-2",
    "MANAGER": "mgr-user-1",
    "AUDITOR_LEAD": "auditor-lead-1",
    "AUDIT_MANAGER": "aum-user-1",
    "APPEAL_REVIEWER": "appeal-rev-1",
}
