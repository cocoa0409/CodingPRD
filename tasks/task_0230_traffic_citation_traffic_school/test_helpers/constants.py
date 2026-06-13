"""Domain thresholds and the standard jurisdiction fee schedule used by fixtures.

The "Jurisdiction A" configuration is the canonical fee schedule the design
recipes build inline; centralizing it here keeps fixtures and tests aligned.
"""

# Standard "Jurisdiction A" fee schedule and policy thresholds (PRD §3.1).
JURISDICTION_A = {
    "name": "Court A",
    "state_code": "CA",
    "base_court_fee_cents": 5000,
    "surcharge_pct": 0.20,
    "late_penalty_cents": 3000,
    "installment_setup_fee_cents": 2500,
    "min_installment_cents": 2000,
    "collections_age_days": 30,
    "collections_fee_pct": 0.25,
    "traffic_school_fee_cents": 4000,
    "school_eligible_max_points": 1,
    "school_cooldown_months": 18,
    "point_suspension_threshold": 4,
    "point_window_months": 12,
}

# Defaults the PRD §3.1 specifies for omittable policy thresholds.
DEFAULT_COLLECTIONS_AGE_DAYS = 30
DEFAULT_SCHOOL_ELIGIBLE_MAX_POINTS = 1
DEFAULT_SCHOOL_COOLDOWN_MONTHS = 18
DEFAULT_POINT_SUSPENSION_THRESHOLD = 4
DEFAULT_POINT_WINDOW_MONTHS = 12

# Pagination defaults (PRD §2.3).
DEFAULT_LIMIT = 10
MAX_LIMIT = 100
