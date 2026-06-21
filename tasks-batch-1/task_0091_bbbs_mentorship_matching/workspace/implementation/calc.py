"""Calculation rules (SCAFFOLD §1.3 / PRD §3.3, §3.6, §3.7).

All decimal outputs use round-half-up to two places, applied exactly once where
the PRD specifies.
"""
from decimal import Decimal, ROUND_HALF_UP

# interest_compatibility_score constants
W_INTEREST = Decimal("0.6")
W_GEO = Decimal("0.25")
W_CAPACITY = Decimal("0.15")
CAPACITY_CAP = 10

# match_compliance_status constants (days)
AMBER_CONTACT_DAYS = 30
RED_CONTACT_DAYS = 60
AMBER_ACTIVITY_DAYS = 45
CONTACT_INTERVAL_DAYS = 30

# outcome_composite_score constants
SOR_W_REL = Decimal("0.5")
SOR_W_OUT = Decimal("0.5")
REMATCH_BONUS = Decimal("0.5")
STRONG_CUTOFF = Decimal("4.0")
MODERATE_CUTOFF = Decimal("2.5")

# background_check_validity
VALIDITY_MONTHS = 24
DMV_ADVERSE_TOLERANCE = 1

# meeting buffer (minutes)
MEETING_BUFFER_MINUTES = 60


def _round2(value):
    """Round-half-up to two decimal places, returned as a float for JSON."""
    q = Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(q)


def compatibility_score(volunteer, child):
    """Weighted score of a volunteer against a child (PRD §3.3).

    score = 0.6*interest + 0.25*geo + 0.15*capacity, summed first, then rounded
    half-up to 2 decimals once (never per-component).
    """
    v_tags = set(volunteer.get("interest_tags") or [])
    c_tags = set(child.get("interest_tags") or [])
    union = v_tags | c_tags
    shared = v_tags & c_tags
    interest_component = (Decimal(len(shared)) / Decimal(len(union))) if union else Decimal(0)

    geo_component = Decimal(1) if volunteer["home_zip"][:3] == child["home_zip"][:3] else Decimal(0)

    capped = min(volunteer["max_weekly_hours"], CAPACITY_CAP)
    capacity_component = Decimal(capped) / Decimal(CAPACITY_CAP)

    weighted_sum = (
        W_INTEREST * interest_component
        + W_GEO * geo_component
        + W_CAPACITY * capacity_component
    )
    return _round2(weighted_sum)


def outcome_composite(relationship_quality, child_outcome, would_rematch):
    """Strength-of-Relationship index (PRD §3.7)."""
    base = SOR_W_REL * Decimal(relationship_quality) + SOR_W_OUT * Decimal(child_outcome)
    bonus = REMATCH_BONUS if would_rematch else Decimal(0)
    composite = _round2(base + bonus)
    band = outcome_band(composite)
    return composite, band


def outcome_band(composite_score):
    """Band a composite score: STRONG >= 4.0, MODERATE >= 2.5, else WEAK.
    Band boundaries are inclusive lower edges (PRD §3.7)."""
    cs = Decimal(str(composite_score))
    if cs >= STRONG_CUTOFF:
        return "STRONG"
    if cs >= MODERATE_CUTOFF:
        return "MODERATE"
    return "WEAK"
