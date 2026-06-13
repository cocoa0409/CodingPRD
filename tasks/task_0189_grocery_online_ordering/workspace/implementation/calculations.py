"""Pricing, totals, split-tender, refund and age calculations.

All money is integer cents (PRD §2.5). The only fractional intermediate is
WEIGHT pricing: unit_price_cents * weight_kg is rounded half-up to whole
cents (PRD §3.4). Order/payment totals round-per-line then sum already
rounded charges (PRD §2.5 / §3.5).
"""
from decimal import Decimal, ROUND_HALF_UP

from timeutil import parse_iso

MIN_AGE_YEARS = 21  # SCAFFOLD calc age_check_outcome; PRD §3.7 "at least 21 years"


def _round_half_up_cents(decimal_value):
    """Round a Decimal product of cents to a whole integer cent, half-up."""
    return int(decimal_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def line_charge(product, qty=None, weight_kg=None):
    """Per-line charge in integer cents (calc line_charge / PRD §3.4).

    UNIT:   unit_price_cents * qty            (qty is an integer each-count)
    WEIGHT: round_half_up(unit_price_cents * weight_kg)
    """
    unit_price = product["unit_price_cents"]
    if product["pricing_mode"] == "UNIT":
        # qty is a whole each-count; product of two integers is exact.
        return int(unit_price) * int(qty)
    else:  # WEIGHT
        product_value = Decimal(str(unit_price)) * Decimal(str(weight_kg))
        return _round_half_up_cents(product_value)


def estimated_total(lines, tip_cents):
    """estimated_total_cents = SUM estimated_line_cents over all lines + tip
    (PRD §3.5). Round-per-line already done; this is an integer sum."""
    return sum(l["estimated_line_cents"] for l in lines) + tip_cents


def estimated_ebt_eligible(lines, product_lookup):
    """SUM estimated_line_cents over lines whose Product.ebt_eligible (PRD
    §3.5); tip excluded."""
    total = 0
    for l in lines:
        prod = product_lookup(l["product_id"])
        if prod and prod.get("ebt_eligible"):
            total += l["estimated_line_cents"]
    return total


def final_total(lines, tip_cents):
    """final_total_cents = SUM final_line_cents over {PICKED,SUBSTITUTED}
    lines + tip (PRD §3.5). OUT_OF_STOCK/CANCELLED contribute 0."""
    total = 0
    for l in lines:
        if l["status"] in ("PICKED", "SUBSTITUTED"):
            total += l["final_line_cents"]
    return total + tip_cents


def final_ebt_eligible(lines, product_lookup, sub_lookup_for_line):
    """SUM final_line_cents over {PICKED,SUBSTITUTED} lines whose EFFECTIVE
    product is ebt_eligible (PRD §3.5). For SUBSTITUTED lines the effective
    product is the substitute product."""
    total = 0
    for l in lines:
        if l["status"] not in ("PICKED", "SUBSTITUTED"):
            continue
        eff = effective_product(l, product_lookup, sub_lookup_for_line)
        if eff and eff.get("ebt_eligible"):
            total += l["final_line_cents"]
    return total


def effective_product(line, product_lookup, sub_lookup_for_line):
    """The product that governs a resolved line: the substitute product for a
    SUBSTITUTED line, otherwise the line's own product (PRD §3.5 / §3.7)."""
    if line["status"] == "SUBSTITUTED":
        sub = sub_lookup_for_line(line["id"])
        if sub is not None:
            p = product_lookup(sub["substitute_product_id"])
            if p is not None:
                return p
    return product_lookup(line["product_id"])


def requires_age_check(lines, product_lookup, sub_lookup_for_line):
    """True if any {PICKED,SUBSTITUTED} line's effective product is
    age_restricted (PRD §3.5 / §3.7)."""
    for l in lines:
        if l["status"] not in ("PICKED", "SUBSTITUTED"):
            continue
        eff = effective_product(l, product_lookup, sub_lookup_for_line)
        if eff and eff.get("age_restricted"):
            return True
    return False


def split_tender(final_ebt_eligible_cents, snap_balance_cents, final_total_cents):
    """Two-bucket waterfall (calc split_tender_allocation / PRD §3.6).

    ebt_charged  = min(E, B)
    card_charged = T - ebt_charged
    """
    ebt_charged = min(final_ebt_eligible_cents, snap_balance_cents)
    card_charged = final_total_cents - ebt_charged
    return ebt_charged, card_charged


def completed_age_years(birth_dt, reference_dt):
    """Whole completed years from birth date to reference date (calc
    age_check_outcome). Both compared on their UTC date components."""
    b = birth_dt.date()
    r = reference_dt.date()
    years = r.year - b.year
    # Subtract one if the birthday has not yet occurred on/before reference.
    if (r.month, r.day) < (b.month, b.day):
        years -= 1
    return years


def age_check_outcome(verified_birth_date_str, slot_window_start_str):
    """PASS if completed age at slot.window_start (UTC date) >= MIN_AGE_YEARS,
    boundary inclusive; else FAIL (calc age_check_outcome / PRD §3.7)."""
    birth = parse_iso(verified_birth_date_str)
    reference = parse_iso(slot_window_start_str)
    age = completed_age_years(birth, reference)
    return "PASS" if age >= MIN_AGE_YEARS else "FAIL"
