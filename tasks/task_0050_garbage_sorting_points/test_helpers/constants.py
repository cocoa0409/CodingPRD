"""Domain thresholds and numeric constants from PRD calculations.

Generic NON_EXISTENT_UUID comes from the framework.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Volume-to-weight conversion constants (PRD §3.3 step 1)
# ---------------------------------------------------------------------------
VOLUME_TO_WEIGHT_KG_PER_L = {
    "RECYCLABLE": 0.150,
    "HAZARDOUS": 0.500,
    "KITCHEN": 0.800,
    "OTHER": 0.300,
}


# ---------------------------------------------------------------------------
# Violation deduction constants (PRD §3.6)
# ---------------------------------------------------------------------------
VIOLATION_DEDUCTION_BY_TYPE = {
    "MIS_SORTING": 20,
    "LITTERING": 50,
    "NO_CLASSIFICATION": 30,
}

# Tiered escalation: largest tier minimum <= count picks the multiplier.
REPEAT_ESCALATION_TIERS = [
    (1, 1.00),
    (2, 1.50),
    (3, 2.00),
    (4, 3.00),
]

# Trailing repeat window in days (PRD §3.6)
REPEAT_WINDOW_DAYS = 30

# Days for the appeal window (PRD §3.6)
APPEAL_WINDOW_DAYS = 14


# ---------------------------------------------------------------------------
# Rule effectiveness scoring (PRD §3.2)
# ---------------------------------------------------------------------------
WEIGHT_VECTOR_BY_TIER = {
    "HIGH": {"accuracy": 0.50, "misjudgment": 0.30, "participation": 0.20},
    "MEDIUM": {"accuracy": 0.40, "misjudgment": 0.40, "participation": 0.20},
    "LOW": {"accuracy": 0.30, "misjudgment": 0.50, "participation": 0.20},
}

PARTICIPATION_HIGH_MIN = 50
PARTICIPATION_MEDIUM_MIN = 10
PARTICIPATION_NORMALIZATION_BASE = 100


# ---------------------------------------------------------------------------
# Ranking score normalization (PRD §3.7)
# ---------------------------------------------------------------------------
MONTHLY_CANONICAL_DAYS = 30
QUALITY_BASELINE = 0.5


# ---------------------------------------------------------------------------
# Disposal validation
# ---------------------------------------------------------------------------
DISPOSAL_BACKDATE_MAX_HOURS = 24


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
def escalation_multiplier_for(repeat_count: int) -> float:
    """Return the multiplier per the tiered escalation table.

    Largest tier minimum <= repeat_count wins.  repeat_count==0 maps to 1.00
    because the violation being recorded is counted (inclusive of this one),
    so the count is always >= 1 in practice.
    """
    mult = 1.00
    for min_count, m in REPEAT_ESCALATION_TIERS:
        if repeat_count >= min_count:
            mult = m
    return mult


def round_half_up(value: float, ndigits: int = 0) -> float:
    """Round half-up — needed because Python's round() does banker's rounding."""
    from decimal import Decimal, ROUND_HALF_UP
    quant = Decimal(10) ** -ndigits if ndigits >= 0 else Decimal(
        10
    ) ** (-ndigits)
    return float(Decimal(str(value)).quantize(quant, rounding=ROUND_HALF_UP))


def accuracy_multiplier(scoring_method: str, accuracy_score: float) -> float:
    """Per PRD §3.3 step 2."""
    if scoring_method == "MANUAL":
        return 0.50 + 0.50 * accuracy_score
    if scoring_method == "AI":
        if accuracy_score >= 0.80:
            return 1.00
        if accuracy_score >= 0.50:
            return 0.70
        return 0.40
    if scoring_method == "SCALE":
        return 1.00
    raise ValueError(f"Unknown scoring_method: {scoring_method}")


__all__ = [
    "VOLUME_TO_WEIGHT_KG_PER_L",
    "VIOLATION_DEDUCTION_BY_TYPE",
    "REPEAT_ESCALATION_TIERS",
    "REPEAT_WINDOW_DAYS",
    "APPEAL_WINDOW_DAYS",
    "WEIGHT_VECTOR_BY_TIER",
    "PARTICIPATION_HIGH_MIN",
    "PARTICIPATION_MEDIUM_MIN",
    "PARTICIPATION_NORMALIZATION_BASE",
    "MONTHLY_CANONICAL_DAYS",
    "QUALITY_BASELINE",
    "DISPOSAL_BACKDATE_MAX_HOURS",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "escalation_multiplier_for",
    "round_half_up",
    "accuracy_multiplier",
]
