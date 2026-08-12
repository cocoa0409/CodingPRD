"""regalia_pricing (scaffold §1.3) and vendor_cancellation_fee."""
from decimal import Decimal, ROUND_HALF_UP

import db


def _round_cents(x):
    """Round a Decimal to whole cents (integer), half up."""
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def price_regalia_order(items, ceremony):
    """Pinned evaluation order:
    (1) tier keyed on PRE-discount subtotal;
    (2) discount rounded PER LINE ITEM then summed;
    (3) late fee on the already-rounded discounted subtotal.
    Returns (subtotal_cents, discount_cents, late_fee_cents, total_cents)."""
    line_totals = []
    for line in items:
        line_totals.append(int(line["unit_price_cents"]) * int(line["quantity"]))
    subtotal = sum(line_totals)

    if subtotal >= 20000:
        pct = Decimal("0.15")
    elif subtotal >= 10000:
        pct = Decimal("0.10")
    else:
        pct = Decimal("0")

    discount = sum(_round_cents(Decimal(lt) * pct) for lt in line_totals)
    discounted = subtotal - discount

    now = db.now_dt()
    deadline = db.parse_dt(ceremony["regalia_order_deadline"])
    if now > deadline:
        late_fee = _round_cents(Decimal(discounted) * Decimal("0.10"))
    else:
        late_fee = 0

    total = discounted + late_fee
    return subtotal, discount, late_fee, total


def vendor_cancellation_fee(contract):
    """now < coverage_start_utc -> 10% (round half up); else 50%. Boundary uses the 0.50 rate (>=)."""
    now = db.now_dt()
    start = db.parse_dt(contract["coverage_start_utc"])
    fee = Decimal(int(contract["fee_cents"]))
    if now < start:
        return _round_cents(fee * Decimal("0.10"))
    return _round_cents(fee * Decimal("0.50"))
