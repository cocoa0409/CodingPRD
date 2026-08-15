"""Calculation rules (SCAFFOLD 1.3 / PRD 2.5, 3.x).

All money is integer cents. Every annotated rounding step is round-half-up.
Rounding order is pinned: tier rate -> net (after discounts) -> digital factor;
per-copy replacement value before the degradation fraction; per-unit conversion
price before quantity multiply; daily base rounded once before tier rates.
"""
from decimal import Decimal, ROUND_HALF_UP

from db import db

LOAN_PERIOD_DAYS = 30
TIER_MULT = {
    "CHAMBER": Decimal("1"),
    "BAND": Decimal("1.5"),
    "ORCHESTRA": Decimal("2"),
}
VOLUME_TIER_1_QTY = 10
VOLUME_TIER_1_DISC = Decimal("0.10")
VOLUME_TIER_2_QTY = 25
VOLUME_TIER_2_DISC = Decimal("0.20")
DIGITAL_FEE_FACTOR = Decimal("0.80")

LATE_TIER_1_DAYS = 7
LATE_TIER_2_DAYS = 30
LATE_RATE_1 = Decimal("0.10")
LATE_RATE_2 = Decimal("0.25")
LATE_RATE_3 = Decimal("0.50")

DAMAGE_CAP_CENTS = 200000
DAMAGE_FLOOR_CENTS = 1500

PERUSAL_DISCOUNT = Decimal("0.15")
PERUSAL_WINDOW_DAYS = 21
QUARANTINE_DAYS = 3

OOP_BASE_DAYS = 45

GRADE_RANK = {"A": 0, "B": 1, "C": 2, "D": 3}
DAMAGE_FRACTIONS = {
    ("A", "B"): Decimal("0.10"),
    ("A", "C"): Decimal("0.30"),
    ("A", "D"): Decimal("0.60"),
    ("B", "C"): Decimal("0.25"),
    ("B", "D"): Decimal("0.50"),
    ("C", "D"): Decimal("0.35"),
}


def D(x):
    """Float-safe Decimal conversion (goes through str to avoid binary noise)."""
    return Decimal(str(x))


def rhu(x):
    """Round half-up to whole cents, returning int."""
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def loan_periods(checkout, due):
    """Number of 30-day periods spanned by [checkout, due), min 1."""
    days = (due - checkout).days
    return max(1, -(-days // LOAN_PERIOD_DAYS))


def estimate_fee(order, work, publisher, periods=None):
    """Provisional rental fee (rental_fee_estimate)."""
    per_copy_per_period = rhu(D(work["base_rental_rate_cents"]) * TIER_MULT[work["ensemble_tier"]])
    lp = periods if periods is not None else order["loan_periods"]
    copies = order["copies_requested"]
    if copies < VOLUME_TIER_1_QTY:
        vol = Decimal("0")
    elif copies < VOLUME_TIER_2_QTY:
        vol = VOLUME_TIER_1_DISC
    else:
        vol = VOLUME_TIER_2_DISC
    gross = per_copy_per_period * lp * copies
    net = rhu(D(gross) * (1 - vol) * (1 - D(publisher["rental_discount_pct"])))
    if order["fulfillment_format"] == "DIGITAL":
        net = rhu(D(net) * DIGITAL_FEE_FACTOR)
    return net


def final_fee(order, work, publisher, return_date):
    """Final fee at check-in (rental_fee_final): base + tiered late surcharge."""
    base = estimate_fee(order, work, publisher)
    late_days = max(0, (return_date - order["due_date"]).days)
    if late_days <= 0:
        return base
    denom = order["loan_periods"] * order["copies_requested"] * LOAN_PERIOD_DAYS
    daily_base = rhu(D(base) / D(denom))
    rate1 = rhu(D(daily_base) * LATE_RATE_1)
    rate2 = rhu(D(daily_base) * LATE_RATE_2)
    rate3 = rhu(D(daily_base) * LATE_RATE_3)
    d1 = min(late_days, LATE_TIER_1_DAYS)
    d2 = min(max(late_days - LATE_TIER_1_DAYS, 0), LATE_TIER_2_DAYS - LATE_TIER_1_DAYS)
    d3 = max(late_days - LATE_TIER_2_DAYS, 0)
    late_cents = (d1 * rate1 + d2 * rate2 + d3 * rate3) * order["copies_requested"]
    return base + late_cents


def per_copy_value(rental_set):
    return rhu(D(rental_set["replacement_value_cents"]) / D(rental_set["copy_count"]))


def damage_charge(checkout_grade, observed_grade, rental_set):
    """damage_charge: 0 when no degradation; per-copy value when LOST; else
    fraction of per-copy value, capped at 200000 and floored at 1500."""
    if observed_grade == "LOST":
        return per_copy_value(rental_set)
    if GRADE_RANK[observed_grade] <= GRADE_RANK[checkout_grade]:
        return 0
    raw = rhu(D(per_copy_value(rental_set)) * DAMAGE_FRACTIONS[(checkout_grade, observed_grade)])
    return max(min(raw, DAMAGE_CAP_CENTS), DAMAGE_FLOOR_CENTS)


def conversion_unit_price(sale_price_cents, discounted):
    """perusal_conversion_credit: round the discounted per-unit price BEFORE
    multiplying by quantity."""
    if discounted:
        return rhu(D(sale_price_cents) * (1 - PERUSAL_DISCOUNT))
    return sale_price_cents


def sourcing_eta_days(work):
    """out_of_print_sourcing_eta."""
    days = OOP_BASE_DAYS
    if work["rights_class"] == "GRAND_RIGHTS":
        days += 30
    if work["rights_class"] == "RESTRICTED":
        days += 60
    for s in db["rental_sets"].values():
        if (
            s["work_id"] == work["id"]
            and s["status"] in ("IN_SERVICE", "UNDER_REPAIR")
            and s["condition_grade"] in ("A", "B")
        ):
            days -= 15
            break
    return max(days, 7)
