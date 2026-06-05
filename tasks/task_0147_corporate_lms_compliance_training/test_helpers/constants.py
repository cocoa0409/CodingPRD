"""Domain thresholds — numeric constants from the PRD's calculations.

CEU score-band multipliers, escalation-tier day boundaries, the per-tier
compliance penalty, and the default due-day windows that the PRD names for
enrollments and path enrollments.
"""

# CEU accrual (SCORE_WEIGHTED): band multipliers keyed off the certifying final_grade.
CEU_TIER_HIGH = 90      # final_grade >= 90 → full multiplier
CEU_TIER_MID = 80       # 80 <= final_grade < 90 → 0.75
CEU_MULT_HIGH = 1.00
CEU_MULT_MID = 0.75
CEU_MULT_LOW = 0.50     # passing but < 80

# Escalation tier: whole days-overdue boundaries.
ESCALATION_TIER1_MAX_DAYS = 7    # 1..7 days → tier 1
ESCALATION_TIER2_MAX_DAYS = 30   # 8..30 days → tier 2; >30 → tier 3

# Compliance score: per-tier penalty subtracted from the compliant-ratio base.
COMPLIANCE_TIER_PENALTY = 5

# Default due-date windows when due_in_days is omitted.
DEFAULT_ENROLLMENT_DUE_DAYS = 30
DEFAULT_PATH_ENROLLMENT_DUE_DAYS = 60

# Course input defaults.
DEFAULT_MAX_ATTEMPTS = 3

# A clearly malformed but well-shaped UUID, for body-FK / path-id not-found probes.
NONEXISTENT_UUID = "00000000-0000-4000-8000-000000000000"
