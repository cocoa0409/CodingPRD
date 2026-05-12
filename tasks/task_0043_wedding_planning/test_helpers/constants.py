"""Domain thresholds — numeric constants from PRD prose.

All values traceable to PRD §3.6 (timeline cap), §3.7 (guest caps and table
limit), and §2.3 (pagination defaults).
"""
from __future__ import annotations


# --- Pagination (PRD §2.3) -------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# --- Guest scale caps (PRD §3.7) -------------------------------------------
# "at most 50 for INTIMATE, at most 200 for MEDIUM, and at most 500 for GRAND"
GUEST_CAP_INTIMATE = 50
GUEST_CAP_MEDIUM = 200
GUEST_CAP_GRAND = 500
GUEST_CAP_BY_SCALE = {
    "INTIMATE": GUEST_CAP_INTIMATE,
    "MEDIUM": GUEST_CAP_MEDIUM,
    "GRAND": GUEST_CAP_GRAND,
}


# --- Per-table seat limit (PRD §3.7) ---------------------------------------
# "the sum of party_size across all guests assigned to the same table MUST
#  not exceed 10 seats"
TABLE_SEAT_LIMIT = 10


# --- Timeline parallel-CEREMONY cap (PRD §3.6) -----------------------------
# "the count of slots active at any single instant ... MUST not exceed two"
MAX_PARALLEL_CEREMONY_SLOTS = 2


# --- Categories required before EXECUTION (PRD §3.1) -----------------------
# "at least one ACCEPTED Contract to exist for each of the VENUE and CATERING
#  vendor categories"
REQUIRED_CATEGORIES_FOR_EXECUTION = frozenset({"VENUE", "CATERING"})


# --- Milestone percent-sum target (PRD §3.1) -------------------------------
# "the sum of percent_of_budget across all milestones on the project MUST
#  equal exactly 100.0"
MILESTONE_PERCENT_TOTAL = 100.0


# --- Performance rating bounds (PRD §3.2) ----------------------------------
PERFORMANCE_RATING_MIN = 1
PERFORMANCE_RATING_MAX = 5


# --- Decimal precision (PRD §2.6) ------------------------------------------
PERFORMANCE_RATING_DECIMALS = 2


__all__ = [
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "GUEST_CAP_INTIMATE",
    "GUEST_CAP_MEDIUM",
    "GUEST_CAP_GRAND",
    "GUEST_CAP_BY_SCALE",
    "TABLE_SEAT_LIMIT",
    "MAX_PARALLEL_CEREMONY_SLOTS",
    "REQUIRED_CATEGORIES_FOR_EXECUTION",
    "MILESTONE_PERCENT_TOTAL",
    "PERFORMANCE_RATING_MIN",
    "PERFORMANCE_RATING_MAX",
    "PERFORMANCE_RATING_DECIMALS",
]
