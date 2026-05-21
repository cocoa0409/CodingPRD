"""Domain thresholds — numeric constants from PRD calculations.

Each constant traces to a verbatim PRD sentence (§2 + §3 narratives).
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
# PRD §2.3: "The limit parameter defaults to 10 when omitted, has a minimum
# value of 1 and a maximum value of 100"
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_MIN_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Post-9/11 GI Bill tier bucket boundaries — PRD §3.1
# ---------------------------------------------------------------------------
# PRD §3.1: "Below 90 days the tier is 0; from 90 up to 180 days the tier
# is 40; from 180 up to 365 days the tier is 50; from 365 up to 547 days
# (eighteen months) the tier is 60; from 547 up to 730 days (two years)
# the tier is 70; from 730 up to 913 days (thirty months) the tier is 80;
# from 913 up to 1095 days (thirty-six months) the tier is 90; and at
# 1095 days or more (three years or more) the tier is 100."
TIER_BUCKETS = [
    (90, 0),
    (180, 40),
    (365, 50),
    (547, 60),
    (730, 70),
    (913, 80),
    (1095, 90),
]
TIER_MAX = 100


def tier_for_days(days: int) -> int:
    """Helper mirroring PRD §3.1 step function (for fixture targeting)."""
    for upper, tier in TIER_BUCKETS:
        if days < upper:
            return tier
    return TIER_MAX


# ---------------------------------------------------------------------------
# Combined-rating ladder — PRD §3.4
# ---------------------------------------------------------------------------
# PRD §2.6: "combined_rating is an integer in the set
# {0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100}"
RATING_LADDER = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
COMBINED_RATING_MIN: int = 0
COMBINED_RATING_MAX: int = 100


# ---------------------------------------------------------------------------
# Tuition caps by program_type — PRD §3.7
# ---------------------------------------------------------------------------
# PRD §3.7: "a PUBLIC_IN_STATE school is treated as effectively uncapped
# (a sentinel ceiling of 100000.00 dollars per term is used) ... a
# PRIVATE_NATIONAL or FOREIGN school caps at 13041.34 dollars per term ...
# a VOC_TECH school caps at 6520.67 dollars per term."
TUITION_MAX_PER_TERM = {
    "PUBLIC_IN_STATE": 100000.00,
    "PRIVATE_NATIONAL": 13041.34,
    "FOREIGN": 13041.34,
    "VOC_TECH": 6520.67,
}


# ---------------------------------------------------------------------------
# Yellow Ribbon — PRD §3.7
# ---------------------------------------------------------------------------
# PRD §3.7: "a Yellow Ribbon match is only available when the veteran's
# post_911_eligibility_tier equals 100"
MIN_TIER_FOR_YELLOW_RIBBON: int = 100


# ---------------------------------------------------------------------------
# Housing allowance — PRD §3.10
# ---------------------------------------------------------------------------
# PRD §3.10: "For an online-only enrollment, the base is half of a fixed
# national-average BAH constant of 1789.00 dollars; the ZIP is not
# consulted."
NATIONAL_AVG_BAH: float = 1789.00
# PRD §3.10: "for each dependent beyond the second, add 50.00 dollars to
# the monthly rate, capped at a total uplift of 200.00 dollars."
UPLIFT_PER_EXTRA_DEP: float = 50.00
UPLIFT_CAP: float = 200.00
# PRD §3.10: "FULL_TIME multiplies by 1.00, THREE_QUARTER by 0.80,
# HALF_TIME by 0.50, and LESS_THAN_HALF by 0.00"
TRAINING_TIME_FACTOR = {
    "FULL_TIME": 1.00,
    "THREE_QUARTER": 0.80,
    "HALF_TIME": 0.50,
    "LESS_THAN_HALF": 0.00,
}


# ---------------------------------------------------------------------------
# Voc Rehab subsistence — PRD §3.11
# ---------------------------------------------------------------------------
# PRD §3.11: "883.00 dollars per month for FULL_TIME_INSTITUTIONAL, 662.00
# for THREE_QUARTER_INSTITUTIONAL, 441.00 for HALF_TIME_INSTITUTIONAL,
# 772.00 for FARM_COOP, and 0.00 for NON_PAY_OJT."
VOC_REHAB_BASE = {
    "FULL_TIME_INSTITUTIONAL": 883.00,
    "THREE_QUARTER_INSTITUTIONAL": 662.00,
    "HALF_TIME_INSTITUTIONAL": 441.00,
    "FARM_COOP": 772.00,
    "NON_PAY_OJT": 0.00,
}
# PRD §3.11: "if the count is 2 or fewer, the uplift is 0.00 dollars;
# if the count exceeds 2, the uplift is 65.00 dollars per dependent beyond
# the second"
VOC_REHAB_DEP_THRESHOLD: int = 2
VOC_REHAB_UPLIFT_PER_EXTRA_DEP: float = 65.00


# ---------------------------------------------------------------------------
# Entitlement counter — PRD §3.9
# ---------------------------------------------------------------------------
# PRD §2.6: "the entitlement counter is capped at 36.00 and never grows
# beyond it."
ENTITLEMENT_CAP: float = 36.00
# PRD §3.9: "set to days-in-program divided by 30, rounded half-up to two
# decimal places."
DAYS_PER_MONTH: float = 30.0


# ---------------------------------------------------------------------------
# Voc Rehab cycling — PRD §3.11
# ---------------------------------------------------------------------------
# PRD §3.11: "when a suspend call raises suspension_count to 3 (i.e., the
# plan is currently ACTIVE with suspension_count already 2, and a third
# suspension fires), the plan transitions in the same request from ACTIVE
# to SUSPENDED and then immediately to TERMINATED."
MAX_SUSPENSIONS: int = 3


# ---------------------------------------------------------------------------
# DENIED -> DENIED_FINAL window — PRD §3.3
# ---------------------------------------------------------------------------
# PRD §3.3: "An unappealed denied claim becomes terminal after 365 days:
# the periodic sweep advances any claim whose decided_at is at least 365
# days in the past and which has not been appealed from DENIED to
# DENIED_FINAL."
DENIED_FINAL_DAYS: int = 365


# ---------------------------------------------------------------------------
# String constraints — PRD §3.1, §3.3, §3.5
# ---------------------------------------------------------------------------
FULL_NAME_MIN_LEN: int = 1
FULL_NAME_MAX_LEN: int = 120
CONDITION_CODE_MIN_LEN: int = 1
CONDITION_CODE_MAX_LEN: int = 32
SCHOOL_NAME_MIN_LEN: int = 1
SCHOOL_NAME_MAX_LEN: int = 200
FACILITY_CODE_LEN: int = 8


# ---------------------------------------------------------------------------
# Test defaults
# ---------------------------------------------------------------------------
TEST_DEFAULTS = {
    "veteran_full_name": "Test Veteran",
    "school_name": "Test University",
    "zip_bah_code": "10001",
    "branch": "ARMY",
    "discharge_status": "HONORABLE",
    "training_mode": "FULL_TIME_INSTITUTIONAL",
}


__all__ = [
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_MIN_OFFSET",
    "TIER_BUCKETS",
    "TIER_MAX",
    "tier_for_days",
    "RATING_LADDER",
    "COMBINED_RATING_MIN",
    "COMBINED_RATING_MAX",
    "TUITION_MAX_PER_TERM",
    "MIN_TIER_FOR_YELLOW_RIBBON",
    "NATIONAL_AVG_BAH",
    "UPLIFT_PER_EXTRA_DEP",
    "UPLIFT_CAP",
    "TRAINING_TIME_FACTOR",
    "VOC_REHAB_BASE",
    "VOC_REHAB_DEP_THRESHOLD",
    "VOC_REHAB_UPLIFT_PER_EXTRA_DEP",
    "ENTITLEMENT_CAP",
    "DAYS_PER_MONTH",
    "MAX_SUSPENSIONS",
    "DENIED_FINAL_DAYS",
    "FULL_NAME_MIN_LEN",
    "FULL_NAME_MAX_LEN",
    "CONDITION_CODE_MIN_LEN",
    "CONDITION_CODE_MAX_LEN",
    "SCHOOL_NAME_MIN_LEN",
    "SCHOOL_NAME_MAX_LEN",
    "FACILITY_CODE_LEN",
    "TEST_DEFAULTS",
]
