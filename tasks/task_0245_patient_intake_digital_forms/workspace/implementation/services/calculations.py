"""Calculation rules (PRD §3.2, §3.6, §3.8; SCAFFOLD §1.3).

All money is integer cents. Fractional coinsurance legs are rounded half up.
"""
from decimal import Decimal, ROUND_HALF_UP

# Constants (SCAFFOLD §1.3 questionnaire_risk_score).
REQUIRED_MULTIPLIER = 2
HIGH_RISK_THRESHOLD = 20


def _round_half_up(value):
    """Round a Decimal/number half-up to an integer number of cents."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def estimate_copay(plan_default_copay_cents):
    """Forward-looking provisional estimate (PRD §3.2 / estimate_copay).

    No eligibility data yet — the estimate uses only the posted office-visit
    copay, ignoring deductible and coinsurance.
    """
    return plan_default_copay_cents


def finalize_eligible(card, facility_fee_cents, copay_rounding):
    """ELIGIBLE branch of finalize_patient_responsibility (PRD §3.6).

    Five legs: three integer (copay, deductible, facility fee) and two
    fractional coinsurance legs. No allowed-amount cap on the combined sum.
    Rounding order is pinned by clinic.copay_rounding.
    """
    plan_copay = card["plan_copay_cents"]
    allowed = card["visit_allowed_amount_cents"]
    deductible = card["remaining_deductible_cents"]
    med_pct = card["plan_coinsurance_pct"]
    fac_pct = card["facility_coinsurance_pct"]

    copay_leg = min(plan_copay, allowed)                 # integer
    deductible_leg = min(deductible, allowed)            # integer
    above_deductible = max(allowed - deductible, 0)
    # Fractional legs kept as exact Decimals before rounding.
    medical_coins_leg = Decimal(above_deductible) * Decimal(med_pct) / Decimal(100)
    facility_coins_leg = Decimal(facility_fee_cents) * Decimal(fac_pct) / Decimal(100)

    if copay_rounding == "SUM_THEN_ROUND":
        total = (Decimal(copay_leg) + Decimal(deductible_leg)
                 + Decimal(facility_fee_cents)
                 + medical_coins_leg + facility_coins_leg)
        return _round_half_up(total)
    # PER_LINE_THEN_SUM (default): round each fractional leg on its own first.
    return (copay_leg + deductible_leg + facility_fee_cents
            + _round_half_up(medical_coins_leg)
            + _round_half_up(facility_coins_leg))


def finalize_self_pay(card, facility_fee_cents):
    """INELIGIBLE / self-pay branch (PRD §3.6).

    Full allowed amount + facility fee, no plan offset, no coinsurance.
    """
    return card["visit_allowed_amount_cents"] + facility_fee_cents


def provisional_responsibility(card, facility_fee_cents):
    """provisional_responsibility_cents on an EligibilityCheck (PRD §3.6).

    Assumes the full deductible is unmet, so coinsurance is never reached:
    copay leg + deductible leg + facility fee, both coinsurance legs zero.
    """
    plan_copay = card["plan_copay_cents"]
    allowed = card["visit_allowed_amount_cents"]
    deductible = card["remaining_deductible_cents"]
    copay_leg = min(plan_copay, allowed)
    deductible_leg = min(deductible, allowed)
    return copay_leg + deductible_leg + facility_fee_cents


def provisional_risk_score(answered_sections):
    """Plain sum of risk_weight at SUBMIT (PRD §3.8)."""
    total = 0
    for s in answered_sections:
        total += int(s.get("risk_weight", 0))
    return total


def final_risk_score(answered_sections, required_sections):
    """Weighted final score at ACCEPT (PRD §3.8).

    Each answered section contributes risk_weight x REQUIRED_MULTIPLIER when its
    section_key is required, x1 otherwise; the weighted sum is rounded half up.
    """
    required = set(required_sections or [])
    total = Decimal(0)
    for s in answered_sections:
        weight = Decimal(int(s.get("risk_weight", 0)))
        multiplier = REQUIRED_MULTIPLIER if s.get("section_key") in required else 1
        total += weight * Decimal(multiplier)
    return _round_half_up(total)


def is_high_risk(score):
    return score >= HIGH_RISK_THRESHOLD


def provider_overlap(new_start, new_end, busy_intervals):
    """provider_busy_interval (PRD §3.2): half-open [start, end+buffer).

    New half-open interval [new_start, new_end) collides iff it overlaps any
    occupied interval. Touching at a single instant does not collide.
    """
    for (start, end) in busy_intervals:
        if new_start < end and start < new_end:
            return True
    return False


def room_overlap(new_start, new_end, booked_intervals):
    """room_busy_interval (PRD §3.11): closed [start, end].

    A new closed interval [new_start, new_end] collides only if it overlaps an
    existing closed interval on more than a single shared endpoint. Adjacency
    (existing.end == new.start) is allowed.
    """
    for (start, end) in booked_intervals:
        # Strict-interior overlap: intervals share more than one endpoint.
        if new_start < end and start < new_end:
            return True
    return False
