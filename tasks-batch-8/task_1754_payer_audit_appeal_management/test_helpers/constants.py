"""Domain thresholds and shared constants from the PRD.

- The logical clock starts at exactly 2026-08-01T00:00:00Z at server startup.
- High-exposure closure requires a DepartmentDirector at or above
  2,500,000 cents of net exposure (PRD case-closure rule).
- The corrective-plan effectiveness window is fourteen days; a plan fails
  permanently when its cycle count reaches three (PRD corrective-action rules).
- Lines or groups with no usable snapshot history fall back to a default of
  five thousand basis points of assumed overturn rate (PRD exposure rules).
- Interest accrues in thirty-day periods (PRD recoupment interest rules).
"""

CLOCK_DEFAULT = "2026-08-01T00:00:00Z"

DIRECTOR_CLOSE_THRESHOLD_CENTS = 2_500_000
CAP_EFFECTIVENESS_WINDOW_DAYS = 14
CAP_MAX_CYCLES = 3
DEFAULT_OVERTURN_BP = 5000
INTEREST_PERIOD_DAYS = 30

SECONDS_PER_DAY = 86_400

# Default payer registration used by fixtures: Medicare (RAC) track, thirty-day
# windows everywhere, generous concurrency cap, no hold levels, 1%/2% interest
# tiers and a 25% interest cap.
DEFAULT_PAYER_CONFIG = {
    "records_submission_days": 30,
    "l1_deadline_days": 30,
    "l2_deadline_days": 30,
    "l3_deadline_days": 30,
    "l4_deadline_days": 30,
    "l5_deadline_days": 30,
    "external_review_deadline_days": 30,
    "concurrent_audit_cap": 10,
    "hold_levels": [],
    "interest_rate_bps_tier1": 100,
    "interest_rate_bps_tier2": 200,
    "interest_cap_pct": 25,
}
