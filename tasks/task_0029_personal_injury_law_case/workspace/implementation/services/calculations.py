"""Calculation rules (scaffold §1.3 / PRD §3.3, §3.4, §3.7).

All monetary amounts are integer cents. Decimal is used wherever a rate
multiplication is involved; rounding is ROUND_HALF_UP for the half-up steps
and explicit floor for the lien waterfall shrink step.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, List, Tuple


# ---- Statute of limitations (calc §1.3 statute_of_limitations_check) ---------

STATUTE_YEARS = {
    "CA": 2,
    "NY": 2,
    "TX": 2,
    "FL": 4,
    "IL": 2,
}


# ---- Demand letter pricing (calc §1.3 demand_letter_amount, PRD §3.4) -------

FUTURE_MED_PV_FACTOR = Decimal("0.85")
TIER_LOW_CENTS = 500000        # $5,000
TIER_HIGH_CENTS = 5000000      # $50,000
BUFFER_RATE_LOW = Decimal("0.20")
BUFFER_RATE_MID = Decimal("0.15")
BUFFER_RATE_HIGH = Decimal("0.10")


def _round_half_up_cents(d: Decimal) -> int:
    """Round a Decimal value half-up to whole cents (integer)."""
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_demand_amount_cents(included_items: List[Dict[str, Any]], pain_multiplier) -> int:
    """Build demand amount per PRD §3.4 — order is pinned.

    Step A: per-category lines, each rounded half-up to whole cents.
       medical_line  = sum(MEDICAL_BILLS amounts) * 1.00
       wages_line    = sum(LOST_WAGES amounts)    * 1.00
       property_line = sum(PROPERTY amounts)      * 1.00
       future_med_line = sum(FUTURE_MEDICAL amounts) * 0.85
       pain_line = (medical_line + wages_line + future_med_line) * m  (rounded)
    Step B: subtotal = sum of the five lines.
    Step C: buffer  = subtotal * tiered_rate (rounded half-up).
    Step D: demand  = subtotal + buffer (pure integer sum, no rounding).
    """
    if not isinstance(pain_multiplier, Decimal):
        pain_multiplier = Decimal(str(pain_multiplier))

    sum_medical = sum(
        int(i["amount_cents"]) for i in included_items if i["category"] == "MEDICAL_BILLS"
    )
    sum_wages = sum(
        int(i["amount_cents"]) for i in included_items if i["category"] == "LOST_WAGES"
    )
    sum_property = sum(
        int(i["amount_cents"]) for i in included_items if i["category"] == "PROPERTY"
    )
    sum_future = sum(
        int(i["amount_cents"]) for i in included_items if i["category"] == "FUTURE_MEDICAL"
    )

    # Step A: per-line rounds — *1.0 lines are integer already, but we still
    # apply the round_half_up call as the contract is explicit about it.
    medical_line   = _round_half_up_cents(Decimal(sum_medical)   * Decimal("1.00"))
    wages_line     = _round_half_up_cents(Decimal(sum_wages)     * Decimal("1.00"))
    property_line  = _round_half_up_cents(Decimal(sum_property)  * Decimal("1.00"))
    future_med_line = _round_half_up_cents(Decimal(sum_future)   * FUTURE_MED_PV_FACTOR)

    # pain line = (medical + wages + future_med) * m, rounded
    pain_base = Decimal(medical_line + wages_line + future_med_line)
    pain_line = _round_half_up_cents(pain_base * pain_multiplier)

    # Step B: subtotal (integer sum — no rounding step here)
    subtotal = medical_line + wages_line + property_line + future_med_line + pain_line

    # Step C: tiered buffer, rounded once
    if subtotal < TIER_LOW_CENTS:
        rate = BUFFER_RATE_LOW
    elif subtotal < TIER_HIGH_CENTS:
        rate = BUFFER_RATE_MID
    else:
        rate = BUFFER_RATE_HIGH
    buffer_cents = _round_half_up_cents(Decimal(subtotal) * rate)

    # Step D: pure integer sum
    return subtotal + buffer_cents


# ---- Contingency fee (calc §1.3 contingency_fee, PRD §3.7) ------------------

PRE_SUIT_RATE = Decimal("0.3333")
POST_SUIT_RATE = Decimal("0.40")


def compute_contingency_fee_cents(gross_settlement_cents: int, filed_in_court: bool) -> int:
    """Single multiply * rate, ROUND_HALF_UP once at the end."""
    rate = POST_SUIT_RATE if filed_in_court else PRE_SUIT_RATE
    return _round_half_up_cents(Decimal(int(gross_settlement_cents)) * rate)


# ---- Lien waterfall (calc §1.3 lien_proportional_cap, PRD §3.7) --------------

def compute_lien_waterfall(
    open_liens_sorted: List[Dict[str, Any]],
    distributable_to_liens: int,
) -> List[Tuple[str, int]]:
    """Return [(lien_id, negotiated_cap_cents), ...] in created_at-ASC order.

    open_liens_sorted MUST already be sorted by created_at ASC. The waterfall:
        1. total_asserted = sum(l.asserted_amount_cents)
        2. if total_asserted <= distributable_to_liens:
               every lien gets its full asserted_amount_cents.
           else:
               shrink_ratio = distributable / total_asserted
               cap_l = floor(asserted_l * shrink_ratio)   per lien
               remainder = distributable - sum(cap_l)     (non-negative)
               distribute remainder cent-by-cent to oldest liens first.
    """
    if not open_liens_sorted:
        return []

    distributable = max(0, int(distributable_to_liens))
    total_asserted = sum(int(l["asserted_amount_cents"]) for l in open_liens_sorted)

    if total_asserted <= distributable:
        return [(l["id"], int(l["asserted_amount_cents"])) for l in open_liens_sorted]

    # Shrink: floor per lien on the shrink ratio
    shrink = Decimal(distributable) / Decimal(total_asserted)
    caps: List[int] = []
    for l in open_liens_sorted:
        floored = (Decimal(int(l["asserted_amount_cents"])) * shrink).to_integral_value(
            rounding="ROUND_FLOOR"
        )
        caps.append(int(floored))

    remainder = distributable - sum(caps)
    # remainder is guaranteed non-negative because each cap was floored.
    # Distribute cent-by-cent to oldest liens first (which is just iteration
    # order over the already-sorted list).
    i = 0
    while remainder > 0 and i < len(caps):
        caps[i] += 1
        remainder -= 1
        i += 1
        if i == len(caps) and remainder > 0:
            # Should not happen given total_asserted > distributable, but guard.
            i = 0

    return [(l["id"], caps[idx]) for idx, l in enumerate(open_liens_sorted)]


# ---- Damages summary (calc §1.3 gross_damages_model, PRD §3.3) --------------

ECONOMIC_CATEGORIES = {"MEDICAL_BILLS", "LOST_WAGES", "FUTURE_MEDICAL", "PROPERTY"}


def compute_damages_summary(included_items: List[Dict[str, Any]]) -> Dict[str, int]:
    """Return {included_total, economic_only, full_model}.

    economic_only sums the four economic categories from INCLUDED items.
    full_model = economic_only + sum of PAIN_SUFFERING amounts on INCLUDED items.
    """
    total = sum(int(i["amount_cents"]) for i in included_items)
    economic_only = sum(
        int(i["amount_cents"]) for i in included_items if i["category"] in ECONOMIC_CATEGORIES
    )
    pain = sum(
        int(i["amount_cents"]) for i in included_items if i["category"] == "PAIN_SUFFERING"
    )
    return {
        "included_total": total,
        "economic_only": economic_only,
        "full_model": economic_only + pain,
    }
