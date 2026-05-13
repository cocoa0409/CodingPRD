"""Domain thresholds — numeric constants from PRD calculations and §2.x.

These are pulled verbatim from the PRD prose so test assertions match the
implementation contract.
"""
from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP


# ===========================================================================
# Acceptance window and stage limits (PRD §2.10)
# ===========================================================================
# "When an Assignment is dispatched, accept_deadline_at is set to
#  dispatched_at plus a fixed acceptance window of 48 hours."
ACCEPT_WINDOW_HOURS = 48

# "When the translator accepts, stage_deadline_at is set to accepted_at plus
#  a role-specific stage limit: 72 hours for TRANSLATOR, 48 hours for REVIEWER,
#  and 24 hours for FINAL_REVIEWER."
STAGE_LIMIT_HOURS = {
    "TRANSLATOR": 72,
    "REVIEWER": 48,
    "FINAL_REVIEWER": 24,
}


# ===========================================================================
# Workload cap (PRD §2.11)
# ===========================================================================
# "The platform caps each translator's open workload at 200 open segments"
MAX_WORKLOAD_SEGMENTS = 200


# ===========================================================================
# Urgency tier boundaries (PRD §3.2)
# ===========================================================================
# "when the remaining hours are strictly less than 48, the tier is CRITICAL;
#  otherwise when the remaining hours are strictly less than 168, the tier
#  is RUSH; otherwise the tier is STANDARD"
CRITICAL_HOURS = 48
RUSH_HOURS = 168


# ===========================================================================
# Repetition multipliers in basis points (PRD §3.2 / §3.7)
# ===========================================================================
REP_TIER_BPS = {
    "NEW": 10000,
    "FUZZY": 6000,
    "TM_LEVERAGE": 3000,
    "EXACT_REPEAT": 1500,
}


# ===========================================================================
# Urgency multipliers in basis points (PRD §3.2 / §3.7)
# ===========================================================================
URGENCY_MULT_BPS = {
    "STANDARD": 10000,
    "RUSH": 12500,
    "CRITICAL": 15000,
}


# ===========================================================================
# Grade multipliers in basis points (PRD §3.7)
# ===========================================================================
# Final payout: JUNIOR=8000, INTERMEDIATE=10000, SENIOR=12000, EXPERT=14000.
# Quote uses a fixed SENIOR-like multiplier of 10000 (the quote's forward-looking
# assumption — PRD §3.2 says "the result is multiplied by the forward-looking
# grade multiplier of 10000").
GRADE_MULT_BPS = {
    "JUNIOR": 8000,
    "INTERMEDIATE": 10000,
    "SENIOR": 12000,
    "EXPERT": 14000,
}

# Quote always uses 10000 (the SENIOR-baseline forward-looking assumption).
QUOTE_GRADE_MULT_BPS = 10000


# ===========================================================================
# Repetition rate gate (PRD §3.2)
# ===========================================================================
# "When that ratio reaches or exceeds 75 percent (the boundary is inclusive:
#  exactly 75.00 percent triggers the gate, 74.99 percent does not)"
REPETITION_HIGH_THRESHOLD_PCT = 75


# ===========================================================================
# TM-leverage thresholds (PRD §3.2)
# ===========================================================================
# "Otherwise, when the fuzzy percentage is at least 95, the segment is
#  classified as TM_LEVERAGE..."
TM_LEVERAGE_PCT_THRESHOLD = 95
# "Otherwise, when the fuzzy percentage is at least 75, the segment is
#  classified as FUZZY..."
FUZZY_PCT_THRESHOLD = 75


# ===========================================================================
# Quality scoring (PRD §3.6 / §3.7)
# ===========================================================================
QUALITY_BAR = 90
QUALITY_DEDUCTION_PER_POINT_BPS = 50
PENALTY_PER_DENSITY_UNIT = 2.5
SEVERITY_WEIGHT = {
    "MINOR": 1,
    "MAJOR": 3,
    "CRITICAL": 9,
}


# ===========================================================================
# Rating window (PRD §3.6)
# ===========================================================================
# "rolling_quality_score is the arithmetic mean of every finalized quality
#  score for the translator whose finalization timestamp lies within the
#  last 90 days"
ROLLING_WINDOW_DAYS = 90


# ===========================================================================
# Pagination defaults (PRD §2.3)
# ===========================================================================
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ===========================================================================
# Helpers — half-up rounding to integer cents
# ===========================================================================
def round_half_up_int(value: float) -> int:
    """PRD §2.8: 'rounded to the nearest integer cent using half-up rounding
    (a fractional 0.5 always rounds away from zero).'"""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value: float) -> float:
    """PRD §2.8: 'When a value's natural precision is fractional rather than
    integer ... the value is rounded to two decimal places, again half-up.'"""
    return float(
        Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )


def expected_quote_per_segment(base_unit_price_cents: int,
                               unit_qty: int,
                               rep_class: str,
                               grade_mult_bps: int = QUOTE_GRADE_MULT_BPS) -> int:
    """Reproduce per-segment quote contribution per PRD §3.2."""
    base_cents = base_unit_price_cents * unit_qty
    rep_bps = REP_TIER_BPS[rep_class]
    rep_adjusted = round_half_up_int(base_cents * rep_bps / 10000)
    graded = round_half_up_int(rep_adjusted * grade_mult_bps / 10000)
    return graded


def expected_quote_total(segments_meta, base_unit_price_cents: int,
                         urgency_tier: str,
                         grade_mult_bps: int = QUOTE_GRADE_MULT_BPS) -> int:
    """Reproduce the quote total per PRD §3.2.

    segments_meta: iterable of (unit_qty, repetition_class) tuples.
    """
    subtotal = sum(
        expected_quote_per_segment(
            base_unit_price_cents, qty, rep, grade_mult_bps,
        )
        for qty, rep in segments_meta
    )
    urg = URGENCY_MULT_BPS[urgency_tier]
    return round_half_up_int(subtotal * urg / 10000)


__all__ = [
    "ACCEPT_WINDOW_HOURS", "STAGE_LIMIT_HOURS",
    "MAX_WORKLOAD_SEGMENTS",
    "CRITICAL_HOURS", "RUSH_HOURS",
    "REP_TIER_BPS", "URGENCY_MULT_BPS",
    "GRADE_MULT_BPS", "QUOTE_GRADE_MULT_BPS",
    "REPETITION_HIGH_THRESHOLD_PCT",
    "TM_LEVERAGE_PCT_THRESHOLD", "FUZZY_PCT_THRESHOLD",
    "QUALITY_BAR", "QUALITY_DEDUCTION_PER_POINT_BPS",
    "PENALTY_PER_DENSITY_UNIT", "SEVERITY_WEIGHT",
    "ROLLING_WINDOW_DAYS",
    "PAGINATION_DEFAULT_LIMIT", "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT", "PAGINATION_DEFAULT_OFFSET",
    "round_half_up_int", "round_half_up_2dp",
    "expected_quote_per_segment", "expected_quote_total",
]
