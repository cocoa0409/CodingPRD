"""Domain thresholds and defaults — numeric constants named in the PRD."""

# Logical clock startup default (PRD §2.11).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

# Documented project defaults (PRD §3.1).
PROJECT_DEFAULTS = {
    "rfi_response_days": 10,
    "ack_required_days": 5,
    "mobilization_buffer_days": 2,
    "long_lead_threshold_days": 30,
    "expedite_window_days": 10,
    "gc_tier_threshold_cents": 1_000_000,
}

# Markup layer rates for the impact cost delta (PRD §3.6).
MARKUP = {
    "SUB_MARKUP_PCT": 0.10,
    "GC_MARKUP_TIER1": 0.05,
    "GC_MARKUP_TIER2": 0.07,
    "BOND_PCT": 0.02,
    "CONTINGENCY_ALLOWANCE_PCT": 0.15,
}

# Escalation tiers on days_late (PRD §3.4).
ESCALATION = {
    "L2_MIN_DAYS": 7,
    "L3_MIN_DAYS": 14,
}

# Expediting priority score weights (PRD §3.4).
PRIORITY_SCORE = {
    "W_LATE": 3,
    "LATE_CAP_DAYS": 20,
    "W_CRIT": 1,
    "W_FLOAT": 2,
    "SCORE_CAP": 100,
    "CRITICAL_POINTS": 40,
    "HIGH_POINTS": 20,
    "STANDARD_POINTS": 0,
}

# Subcontractor standing thresholds on late_ack_count (PRD §3.8).
STANDING = {
    "WATCH_LATE_ACKS": 3,
    "SUSPENDED_LATE_ACKS": 6,
}

# Reviewer defaults (PRD §3.1).
REVIEWER_DEFAULT_CAPACITY = 3
