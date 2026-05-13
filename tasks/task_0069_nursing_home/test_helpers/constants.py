"""Domain thresholds and numeric constants from the PRD.

These are intentionally pulled from PRD prose:
- §2.7 (validation priority — admission deposit floor 5,000.00)
- §3.2 (care-level classification weights and thresholds)
- §3.3 (care-plan review-cycle days by level)
- §3.6 (epidemic config defaults)
- §3.7 (per-level daily/hourly rates, meal unit, subsidy rates,
  monthly subsidy cap 2,000.00, insurance rate 70%)
"""
from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Admission deposit floor (PRD §2.7 #23)
# ---------------------------------------------------------------------------
REQUIRED_ADMISSION_DEPOSIT_CENTS = 500_000   # 5,000.00


# ---------------------------------------------------------------------------
# Care-level classification (PRD §3.2)
# ---------------------------------------------------------------------------
W_ADL = 0.5
W_COG = 1.0
W_MED = 1.0

ADL_MAX = 100
COG_MAX = 30
MED_MAX = 50

# Inclusive lower-bound classification thresholds (PRD §3.2)
COMPOSITE_THRESHOLD_INTENSIVE = 80
COMPOSITE_THRESHOLD_L4 = 60
COMPOSITE_THRESHOLD_L3 = 40
COMPOSITE_THRESHOLD_L2 = 20


# ---------------------------------------------------------------------------
# Waitlist (PRD §3.1)
# ---------------------------------------------------------------------------
CARE_LEVEL_WEIGHT = {
    "L1": 1, "L2": 2, "L3": 3, "L4": 4, "INTENSIVE": 5,
}


# ---------------------------------------------------------------------------
# Care-plan review cycle (PRD §3.3)
# ---------------------------------------------------------------------------
REVIEW_CYCLE_BY_LEVEL = {
    "L1": 90, "L2": 60, "L3": 45, "L4": 30, "INTENSIVE": 14,
}


# ---------------------------------------------------------------------------
# Billing — package vs a-la-carte rates (PRD §3.7)
# ---------------------------------------------------------------------------
PACKAGE_DAILY_CARE_CENTS = {
    "L1": 5_000, "L2": 8_000, "L3": 12_000, "L4": 18_000, "INTENSIVE": 30_000,
}
PACKAGE_DAILY_MEAL_CENTS = 4_000

HOURLY_CARE_RATE_CENTS = {
    "L1": 3_000, "L2": 4_500, "L3": 6_500, "L4": 9_000, "INTENSIVE": 15_000,
}
MEAL_UNIT_CENTS = 1_500


# ---------------------------------------------------------------------------
# Government subsidy / insurance (PRD §3.7)
# ---------------------------------------------------------------------------
SUBSIDY_RATE_BY_LEVEL = {
    "L1": 0.10, "L2": 0.15, "L3": 0.20, "L4": 0.30, "INTENSIVE": 0.40,
}
GOV_SUBSIDY_MONTHLY_CAP_CENTS = 200_000   # 2,000.00
INSURANCE_COVERAGE_RATE = 0.70


# ---------------------------------------------------------------------------
# Epidemic posture defaults (PRD §3.6)
# ---------------------------------------------------------------------------
DEFAULT_MAX_TEMPERATURE_C = 37.3
DEFAULT_MAX_VISITORS_PER_DAY = 2


# ---------------------------------------------------------------------------
# Visit slot duration limits (PRD §2.7 #17 / §3.6)
# ---------------------------------------------------------------------------
VISIT_SLOT_MIN_MINUTES = 15
VISIT_SLOT_MAX_MINUTES = 120


# ---------------------------------------------------------------------------
# Care-task recording window (PRD §2.7 #18 / §3.3)
# ---------------------------------------------------------------------------
TASK_RECORD_WINDOW_HOURS = 4


# ---------------------------------------------------------------------------
# Reassessment / archive / waitlist offer timers (PRD §2.11)
# ---------------------------------------------------------------------------
REASSESSMENT_DAYS = 90
SUPERSEDED_ARCHIVE_DAYS = 30
WAITLIST_OFFER_HOURS = 24


# ---------------------------------------------------------------------------
# Helpers — keep test arithmetic identical to PRD pinned semantics
# ---------------------------------------------------------------------------
def round_half_up_int(value) -> int:
    """PRD §2.6: 'round half up' for pro-rated/per-line monetary values."""
    return int(
        Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


def round_half_up_2dp(value) -> float:
    """PRD §2.6 / §3.2: composite_score 'rounded half up to two decimal places'."""
    return float(
        Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )


def expected_composite_score(adl: int, cog: int, med: int) -> float:
    """PRD §3.2 — exact verbatim composite formula:
    (100 - adl)*0.5 + (30 - cog)*1.0 + medical_condition_score*1.0
    rounded half up to two decimal places."""
    return round_half_up_2dp(
        (ADL_MAX - adl) * W_ADL
        + (COG_MAX - cog) * W_COG
        + med * W_MED,
    )


def expected_classification(composite: float) -> str:
    """PRD §3.2 — inclusive lower-bound thresholds."""
    if composite >= COMPOSITE_THRESHOLD_INTENSIVE:
        return "INTENSIVE"
    if composite >= COMPOSITE_THRESHOLD_L4:
        return "L4"
    if composite >= COMPOSITE_THRESHOLD_L3:
        return "L3"
    if composite >= COMPOSITE_THRESHOLD_L2:
        return "L2"
    return "L1"


__all__ = [
    "PAGINATION_DEFAULT_LIMIT", "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT", "PAGINATION_DEFAULT_OFFSET",
    "REQUIRED_ADMISSION_DEPOSIT_CENTS",
    "W_ADL", "W_COG", "W_MED",
    "ADL_MAX", "COG_MAX", "MED_MAX",
    "COMPOSITE_THRESHOLD_INTENSIVE", "COMPOSITE_THRESHOLD_L4",
    "COMPOSITE_THRESHOLD_L3", "COMPOSITE_THRESHOLD_L2",
    "CARE_LEVEL_WEIGHT", "REVIEW_CYCLE_BY_LEVEL",
    "PACKAGE_DAILY_CARE_CENTS", "PACKAGE_DAILY_MEAL_CENTS",
    "HOURLY_CARE_RATE_CENTS", "MEAL_UNIT_CENTS",
    "SUBSIDY_RATE_BY_LEVEL", "GOV_SUBSIDY_MONTHLY_CAP_CENTS",
    "INSURANCE_COVERAGE_RATE",
    "DEFAULT_MAX_TEMPERATURE_C", "DEFAULT_MAX_VISITORS_PER_DAY",
    "VISIT_SLOT_MIN_MINUTES", "VISIT_SLOT_MAX_MINUTES",
    "TASK_RECORD_WINDOW_HOURS",
    "REASSESSMENT_DAYS", "SUPERSEDED_ARCHIVE_DAYS", "WAITLIST_OFFER_HOURS",
    "round_half_up_int", "round_half_up_2dp",
    "expected_composite_score", "expected_classification",
]
