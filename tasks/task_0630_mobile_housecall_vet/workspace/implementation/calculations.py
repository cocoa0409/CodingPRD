"""Calculation rules (PRD §3, SCAFFOLD §1.3).

All money is integer cents. Per-line round-half-up then sum. Dosing and
reconciliation work to 1 decimal place, round-half-up.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

# Constants (SCAFFOLD §1.3)
DOSE_PER_KG_ML = Decimal("0.2")
MIN_FLOOR_ML = Decimal("1.0")
TRAVEL_BUFFER_MIN = 30


def _d(x):
    """Coerce a JSON number (int/float) to Decimal without float noise."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, bool):
        return Decimal(int(x))
    if isinstance(x, int):
        return Decimal(x)
    # str() of a float keeps the shortest round-trip repr, avoiding 0.1 noise.
    return Decimal(str(x))


def round_half_up_cents(value):
    """Round a Decimal money amount to whole cents, round-half-up -> int."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_1dp(value):
    """Round a Decimal to 1 decimal place, round-half-up -> float."""
    q = value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(q)


def estimate_total(line_items, travel_surcharge_cents):
    """ROUND-PER-LINE-THEN-SUM. Returns (subtotal_cents, estimate_total_cents)."""
    subtotal = 0
    for li in line_items:
        line_cents = round_half_up_cents(_d(li["unit_cents"]) * _d(li["qty"]))
        subtotal += line_cents
    total = subtotal + int(travel_surcharge_cents)
    return subtotal, total


def invoice_total(line_items, travel_surcharge_cents, administered_vaccine_doses):
    """FINAL variant: VACCINE_DOSE lines capped at administered doses.

    Per-line round-half-up then sum; travel surcharge always added.
    """
    invoice_cents = 0
    for li in line_items:
        billable_qty = _d(li["qty"])
        if li.get("code") == "VACCINE_DOSE":
            cap = _d(administered_vaccine_doses)
            if cap < billable_qty:
                billable_qty = cap
        line_cents = round_half_up_cents(_d(li["unit_cents"]) * billable_qty)
        invoice_cents += line_cents
    return invoice_cents + int(travel_surcharge_cents)


def euthanasia_required_ml(weight_kg):
    """Minimum legal DISPENSE dose: max(weight*0.2, 1.0), 1dp round-half-up."""
    raw = _d(weight_kg) * DOSE_PER_KG_ML
    required = max(raw, MIN_FLOOR_ML)
    return round_half_up_1dp(required)


def next_reminder(anchor_date, interval_days, current_clock):
    """Step anchor forward by interval_days until strictly after the clock."""
    nxt = anchor_date
    step = timedelta(days=int(interval_days))
    # Strict comparison: landing exactly on the clock instant is not in the future.
    while nxt <= current_clock:
        nxt = nxt + step
    return nxt
