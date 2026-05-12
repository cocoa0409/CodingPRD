"""Domain thresholds extracted from the PRD.

Numeric constants pinned by PRD §3.3 (PO tier thresholds), §3.9 (three-way
match tolerances and allowed tax rates), §2.3 (pagination), and §3.4
(deadline / escalation extension).
"""
from __future__ import annotations
from typing import List


# ---------------------------------------------------------------------------
# PO tier thresholds (PRD §3.3)
# ---------------------------------------------------------------------------
# "TIER1_MAX_CENTS is 500,000 cents (five thousand dollars), TIER2_MAX_CENTS
# is 5,000,000 cents (fifty thousand dollars), and TIER3_MAX_CENTS is
# 50,000,000 cents (five hundred thousand dollars)."
TIER1_MAX_CENTS: int = 500_000
TIER2_MAX_CENTS: int = 5_000_000
TIER3_MAX_CENTS: int = 50_000_000


# ---------------------------------------------------------------------------
# Quote scoring weights (PRD §3.2)
# ---------------------------------------------------------------------------
# "weights pinned at W_TECH of 0.40 and W_COMM of 0.60"
W_TECH: float = 0.40
W_COMM: float = 0.60


# ---------------------------------------------------------------------------
# Three-way match tolerances (PRD §3.9)
# ---------------------------------------------------------------------------
# "QTY_TOLERANCE_PCT, which is 0.02 (two percent)"
# "AMT_TOLERANCE_PCT, which is 0.01 (one percent)"
# "TAX_TOLERANCE_CENTS, which is one cent"
QTY_TOLERANCE_PCT: float = 0.02
AMT_TOLERANCE_PCT: float = 0.01
TAX_TOLERANCE_CENTS: int = 1


# Allowed tax rates (PRD §3.9: "ALLOWED_TAX_RATES: 0.06, 0.09, or 0.13").
ALLOWED_TAX_RATES: List[float] = [0.06, 0.09, 0.13]


# ---------------------------------------------------------------------------
# Approval deadline hours (PRD §3.3, §3.4)
# ---------------------------------------------------------------------------
# "deadline_at set to 72 hours after step activation"
APPROVAL_DEADLINE_HOURS: int = 72
# "the step's deadline_at is extended to 24 hours after the moment of escalation"
ESCALATION_EXTENSION_HOURS: int = 24


# ---------------------------------------------------------------------------
# Quote shortlist minimum (PRD §3.3)
# ---------------------------------------------------------------------------
# "there must be at least 3 quotes in SHORTLISTED status on this requirement"
MIN_SHORTLISTED_QUOTES: int = 3


# ---------------------------------------------------------------------------
# Receipt quality threshold (PRD §3.8)
# ---------------------------------------------------------------------------
# "quality_rating at least 60"
QUALITY_RATING_MIN: int = 60


# ---------------------------------------------------------------------------
# Pagination defaults (PRD §2.3)
# ---------------------------------------------------------------------------
# "default limit is 10; the minimum is 1; the maximum is 100. The default
# offset is 0; it must be greater than or equal to 0."
PAGINATION_DEFAULT_LIMIT: int = 10
PAGINATION_MIN_LIMIT: int = 1
PAGINATION_MAX_LIMIT: int = 100
PAGINATION_DEFAULT_OFFSET: int = 0


# ---------------------------------------------------------------------------
# Logical-clock baseline for deterministic time math.
# Tests build all timestamps relative to this instant.
# ---------------------------------------------------------------------------
CLOCK_BASELINE_ISO: str = "2030-03-01T00:00:00.000Z"
FAR_FUTURE_ISO: str = "2099-12-31T23:59:59.000Z"


__all__ = [
    "TIER1_MAX_CENTS",
    "TIER2_MAX_CENTS",
    "TIER3_MAX_CENTS",
    "W_TECH",
    "W_COMM",
    "QTY_TOLERANCE_PCT",
    "AMT_TOLERANCE_PCT",
    "TAX_TOLERANCE_CENTS",
    "ALLOWED_TAX_RATES",
    "APPROVAL_DEADLINE_HOURS",
    "ESCALATION_EXTENSION_HOURS",
    "MIN_SHORTLISTED_QUOTES",
    "QUALITY_RATING_MIN",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "CLOCK_BASELINE_ISO",
    "FAR_FUTURE_ISO",
]
