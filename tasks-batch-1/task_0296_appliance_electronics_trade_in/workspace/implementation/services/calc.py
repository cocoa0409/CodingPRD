"""Pricing-engine calculations (PRD 3.4, 3.6; scaffold Table 3).

All money is integer cents. Multiplying cents by a fractional factor rounds
half-up to whole cents; pure sums/differences add no rounding.
"""
from util import mult_round_half_up


def graded_value(model, grade, defects, powers_on):
    """Condition-graded subtotal in integer cents (calc: graded_value).

    multiplier  = model.condition_multipliers[grade]
    conditioned = round_half_up(base_value_cents * multiplier)
    deduction   = sum(defect_deductions[d] for d in defects)
    Non-powering override: if powers_on is False, conditioned is recomputed with
    the POOR multiplier, and the WONT_POWER_ON deduction is added (once) even if
    it was not in the defect list.
    graded_subtotal = max(0, conditioned - deduction), floored at 0.
    """
    multipliers = model["condition_multipliers"]
    deductions = model["defect_deductions"]

    conditioned = mult_round_half_up(model["base_value_cents"], multipliers[grade])

    deduction_total = 0
    for d in defects:
        deduction_total += int(deductions[d])

    if powers_on is False:
        conditioned = mult_round_half_up(model["base_value_cents"], multipliers["POOR"])
        if "WONT_POWER_ON" not in defects:
            deduction_total += int(deductions["WONT_POWER_ON"])

    return max(0, conditioned - deduction_total)


def promo_bonus(graded_subtotal_cents, campaign):
    """Promotion bonus in integer cents (calc: promo_bonus).

    Order is pinned: round the percentage part FIRST, add the flat part SECOND,
    then clamp the SUM to bonus_cap_cents.
    Returns 0 when no campaign resolved.
    """
    if campaign is None:
        return 0
    pct_part = mult_round_half_up(graded_subtotal_cents, campaign.get("bonus_pct", 0))
    flat_part = int(campaign.get("bonus_flat_cents", 0))
    raw_bonus = pct_part + flat_part
    cap = int(campaign["bonus_cap_cents"])
    return min(raw_bonus, cap)


def quote_amount(graded_subtotal_cents, promo_bonus_cents):
    """amount = graded_subtotal + promo_bonus (pure sum, no re-rounding)."""
    return graded_subtotal_cents + promo_bonus_cents


def inspection_outcome(inspected, locked_amount, tolerance_pct, recycle_floor):
    """Select the inspection outcome (calc: inspection_outcome).

    Evaluation order is pinned: recycle-floor check FIRST, then tolerance band.
      - inspected <= floor                -> RECYCLE
      - inspected >= locked - band        -> MATCH   (band = round_half_up(locked*tol))
      - otherwise                         -> REQUOTE
    """
    if inspected <= recycle_floor:
        return "RECYCLE"
    band = mult_round_half_up(locked_amount, tolerance_pct)
    min_acceptable = locked_amount - band
    if inspected >= min_acceptable:
        return "MATCH"
    return "REQUOTE"
