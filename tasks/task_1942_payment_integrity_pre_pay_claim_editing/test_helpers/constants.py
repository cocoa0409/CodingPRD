"""Domain thresholds and shared values — numeric constants from the PRD."""

# Fixed startup reading of the logical clock (PRD: the logical clock section).
DEFAULT_CLOCK_ISO = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    # High-dollar flag: total_billed_cents >= 10000000 flags (inclusive).
    "HIGH_DOLLAR_THRESHOLD_CENTS": 10000000,
    # Itemized bill review: documents due 30 days out; occupancy buffer 14 days.
    "IBR_DOCUMENTS_DUE_DAYS": 30,
    "IBR_OCCUPANCY_BUFFER_DAYS": 14,
    # Edit auto-suspension: fp_rate >= 0.25 with at least 4 resolved hits.
    "FP_SUSPEND_THRESHOLD": 0.25,
    "FP_MIN_SAMPLE": 4,
    # Reviewer capacity: fewer than 3 IN_REVIEW tasks to accept an assignment.
    "MAX_IN_REVIEW_TASKS": 3,
    # Dispute window: no later than 45 days after determined_at (inclusive).
    "DISPUTE_WINDOW_DAYS": 45,
    # Decision deadline: no later than 60 days after submitted_at (inclusive).
    "DECISION_DEADLINE_DAYS": 60,
    # Readmission window: gap 0..30 days inclusive flags.
    "READMISSION_WINDOW_DAYS": 30,
    # Abrasion tiers keyed on standard_index.
    "TIER_MEDIUM_MIN": 0.25,
    "TIER_HIGH_MIN": 0.50,
    # Abrasion blend weights.
    "WEIGHT_OVERTURN": 0.6,
    "WEIGHT_FP": 0.4,
}

# DRG pricing constants (PRD claim screening section).
BASE_RATE_CENTS = 1000000
DRG_WEIGHTS = {"470": 1.5, "193": 0.95, "392": 0.72}
MEAN_LOS = {"470": 5, "193": 4, "392": 3}
OUTLIER_LOS_THRESHOLD = 10
OUTLIER_PER_DIEM_CENTS = 50000
OUTLIER_CAP_PCT = 0.20

# Itemized bill review contract discount (6.5 percent).
CONTRACT_DISCOUNT = 0.065
