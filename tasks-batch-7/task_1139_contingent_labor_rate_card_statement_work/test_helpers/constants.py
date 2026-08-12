"""Domain thresholds and constants stated in the PRD."""

# Logical clock default at server startup (PRD: reads exactly this before any set call).
DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"

# Tenure (PRD section on worker registration, assignment booking, and tenure)
TENURE_LIMIT_DAYS = 730
TENURE_RISK_WARN_DAYS = 700

# Markup caps per supplier tier (PRD markup transparency check)
TIER_MARKUP_CAP = {
    "PREFERRED": 0.25,
    "APPROVED": 0.20,
    "PROBATION": 0.15,
}

# Distribution selector (PRD supplier distribution section)
DISTRIBUTION_FANOUT = 3
PARALLEL_CAP_PREFERRED = 5
PARALLEL_CAP_APPROVED = 3
NULL_SCORE_AS = 70
RESPONSE_WINDOW_DAYS = 7

# Supplier tier scoring (PRD tiering section)
MIN_PLACEMENTS_FOR_SCORING = 3
TIER_BAND_PREFERRED_MIN = 85
TIER_BAND_APPROVED_MIN = 70

# Invoice processing fee (PRD invoice consolidation section)
FEE_TIER_THRESHOLD_CENTS = 10_000_000
FEE_RATE_BELOW = 0.015
FEE_RATE_AT_OR_ABOVE = 0.010
LINE_INVOICE_FEE_CENTS = 5000

# Conversion fee (PRD conversion section)
CONVERSION_BASE_FEE_CENTS = 2_500_000
PRORATA_HORIZON_DAYS = 730

# Budget-utilization audit threshold (PRD approval cascade)
BUDGET_AUDIT_THRESHOLD_PCT = 95

# Timesheet hours ceiling (PRD timesheet billing section)
SUBMITTED_HOURS_MAX = 60.00
