"""Domain thresholds and shared defaults.

Numeric constants reflect PRD §3 calculation thresholds verbatim. Default
test values for windows / departments / amounts are factory-shared so
tests can override individually.
"""
from __future__ import annotations


# --- Calculation thresholds (PRD §3.10) ---------------------------------
# Tiered base-tax boundaries in cents (lower-inclusive, upper-exclusive).
TAX_TIER_BOUNDARIES_CENTS = [0, 500_000, 2_000_000, 5_000_000, 1_000_000_000]
TAX_TIER_RATES_PERCENT = [0, 3, 10, 20]
SURCHARGE_RATE_PER_MILLE = 3            # 0.3% education-fund surcharge

# PRD §3.10: "when the record's `net_cents` is at least 1,000,000 cents …
# the record's `payment_channel` is overridden to `BANK`".
ROUTING_THRESHOLD_CENTS = 1_000_000

# PRD §3.6 default: "default 200, i.e. |z| of 2.00".
DEFAULT_OUTLIER_Z_THRESHOLD_X100 = 200

# PRD §3.3: "extended by an additional three days".
DUPLICATE_BUFFER_DAYS = 3


# --- Pagination (PRD §2.3) ----------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# --- Test defaults (used only for factories; not from PRD constants) -----
DEFAULT_STUDENT_DEPT = "STU-DEPT"
DEFAULT_REVIEWER_DEPT = "REV-DEPT"
DEFAULT_MAJOR = "CS"
DEFAULT_GRADE = 3
DEFAULT_GPA_X100 = 400


__all__ = [
    "TAX_TIER_BOUNDARIES_CENTS",
    "TAX_TIER_RATES_PERCENT",
    "SURCHARGE_RATE_PER_MILLE",
    "ROUTING_THRESHOLD_CENTS",
    "DEFAULT_OUTLIER_Z_THRESHOLD_X100",
    "DUPLICATE_BUFFER_DAYS",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "DEFAULT_STUDENT_DEPT",
    "DEFAULT_REVIEWER_DEPT",
    "DEFAULT_MAJOR",
    "DEFAULT_GRADE",
    "DEFAULT_GPA_X100",
]
