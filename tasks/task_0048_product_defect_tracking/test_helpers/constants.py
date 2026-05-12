"""Domain thresholds and numeric constants drawn from the PRD prose.

Every constant in this file corresponds to a number that PRD §2 or §3 names
explicitly. Keeping them in one place lets every test refer to "the same"
threshold rather than re-deriving it.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Severity priority-score weights (PRD §3.4)
# ---------------------------------------------------------------------------
SEVERITY_WEIGHT: dict = {
    "BLOCKER": 100,
    "CRITICAL": 70,
    "MAJOR": 40,
    "MINOR": 20,
    "TRIVIAL": 5,
}

IMPACT_WEIGHT: dict = {
    "REVENUE_BLOCKING": 50,
    "CUSTOMER_FACING": 25,
    "INTERNAL": 5,
    "UNKNOWN": 0,
}

# Age factor branching (PRD §3.4)
AGE_DIVISOR_HIGH = 10        # BLOCKER / CRITICAL
AGE_DIVISOR_LOW = 60         # MAJOR / MINOR / TRIVIAL
AGE_CAP_HIGH = 50            # BLOCKER / CRITICAL cap
AGE_CAP_LOW = 30             # MAJOR / MINOR / TRIVIAL cap
REOPEN_MULTIPLIER = 15       # per-reopen bonus in priority_score

# ---------------------------------------------------------------------------
# Multiplier tier thresholds (PRD §3.4)
# ---------------------------------------------------------------------------
MULT_URGENT_THRESHOLD = 150     # score >= 150 -> 0.5
MULT_STANDARD_THRESHOLD = 80    # 80 <= score < 150 -> 1.0
MULTIPLIER_URGENT = 0.5
MULTIPLIER_STANDARD = 1.0
MULTIPLIER_RELAXED = 1.5

# ---------------------------------------------------------------------------
# Response / Resolution SLA base minutes (PRD §3.4)
# ---------------------------------------------------------------------------
RESPONSE_SLA_BASE: dict = {
    "BLOCKER": 30,
    "CRITICAL": 60,
    "MAJOR": 240,
    "MINOR": 480,
    "TRIVIAL": 1440,
}

RESOLUTION_SLA_BASE: dict = {
    "BLOCKER": 240,
    "CRITICAL": 480,
    "MAJOR": 1440,
    "MINOR": 4320,
    "TRIVIAL": 10080,
}

# ---------------------------------------------------------------------------
# Defect density per-defect weights (PRD §3.13)
# ---------------------------------------------------------------------------
DENSITY_WEIGHT: dict = {
    "BLOCKER": 3.0,
    "CRITICAL": 2.0,
    "MAJOR": 1.0,
    "MINOR": 0.5,
    "TRIVIAL": 0.25,
}

# ---------------------------------------------------------------------------
# Regression cooldown (PRD §3.10)
# ---------------------------------------------------------------------------
REGRESSION_COOLDOWN_MINUTES = 10

# ---------------------------------------------------------------------------
# Attachment per-type byte caps (PRD §3.11)
# ---------------------------------------------------------------------------
ATTACHMENT_SIZE_CAP: dict = {
    "SCREENSHOT": 5_242_880,    # 5 MB
    "LOG": 10_485_760,          # 10 MB
    "VIDEO": 209_715_200,       # 200 MB
}

# ---------------------------------------------------------------------------
# Duplicate-link similarity threshold (PRD §3.11)
# ---------------------------------------------------------------------------
DUPLICATE_LINK_MIN_SIMILARITY = 0.5

# ---------------------------------------------------------------------------
# Escalation levels (PRD §3.8)
# ---------------------------------------------------------------------------
ESCALATION_LEVEL_NONE = 0
ESCALATION_LEVEL_RESPONSE = 1
ESCALATION_LEVEL_RESOLUTION = 2

# ---------------------------------------------------------------------------
# Pagination defaults (PRD §2.3)
# ---------------------------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


# ---------------------------------------------------------------------------
# Helpers for derived values that tests need to reproduce.
# ---------------------------------------------------------------------------
import math


def severity_priority_score(
    severity: str, business_impact: str,
    age_minutes: int, reopen_count: int,
) -> int:
    """Replicate PRD §3.4's priority_score formula for tests that need to
    predict the post-mutation value."""
    sw = SEVERITY_WEIGHT[severity]
    iw = IMPACT_WEIGHT[business_impact]
    age = max(0, age_minutes)
    if severity in ("BLOCKER", "CRITICAL"):
        age_factor = min(AGE_CAP_HIGH, age // AGE_DIVISOR_HIGH)
    else:
        age_factor = min(AGE_CAP_LOW, age // AGE_DIVISOR_LOW)
    reopen_bonus = REOPEN_MULTIPLIER * reopen_count
    return sw + iw + age_factor + reopen_bonus


def multiplier_for_score(score: int) -> float:
    if score >= MULT_URGENT_THRESHOLD:
        return MULTIPLIER_URGENT
    if score >= MULT_STANDARD_THRESHOLD:
        return MULTIPLIER_STANDARD
    return MULTIPLIER_RELAXED


def effective_response_sla(severity: str, priority_score: int) -> int:
    """PRD §3.4: effective response SLA = ceil(base * multiplier)."""
    base = RESPONSE_SLA_BASE[severity]
    return math.ceil(base * multiplier_for_score(priority_score))


def effective_resolution_sla(severity: str, priority_score: int) -> int:
    """PRD §3.4: effective resolution SLA = ceil(base * multiplier)."""
    base = RESOLUTION_SLA_BASE[severity]
    return math.ceil(base * multiplier_for_score(priority_score))


__all__ = [
    "SEVERITY_WEIGHT",
    "IMPACT_WEIGHT",
    "AGE_DIVISOR_HIGH",
    "AGE_DIVISOR_LOW",
    "AGE_CAP_HIGH",
    "AGE_CAP_LOW",
    "REOPEN_MULTIPLIER",
    "MULT_URGENT_THRESHOLD",
    "MULT_STANDARD_THRESHOLD",
    "MULTIPLIER_URGENT",
    "MULTIPLIER_STANDARD",
    "MULTIPLIER_RELAXED",
    "RESPONSE_SLA_BASE",
    "RESOLUTION_SLA_BASE",
    "DENSITY_WEIGHT",
    "REGRESSION_COOLDOWN_MINUTES",
    "ATTACHMENT_SIZE_CAP",
    "DUPLICATE_LINK_MIN_SIMILARITY",
    "ESCALATION_LEVEL_NONE",
    "ESCALATION_LEVEL_RESPONSE",
    "ESCALATION_LEVEL_RESOLUTION",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "severity_priority_score",
    "multiplier_for_score",
    "effective_response_sla",
    "effective_resolution_sla",
]
