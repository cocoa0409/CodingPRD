"""Calculation rules (PRD §3.7 / SCAFFOLD Table 3).

All money is integer cents. All rate*hours products round half up to whole
cents. Rounding ORDER is pinned per the PRD and must not be reordered.
"""

from decimal import Decimal, ROUND_HALF_UP

# Constants (from PRD §3.7 and SCAFFOLD difficulty design).
COMPLEX_TIER1_HOURS = Decimal("2.0")
COMPLEX_TIER1_PCT = Decimal("0.10")
COMPLEX_TIER2_PCT = Decimal("0.15")
HOURS_ROUNDING_PLACES = 1
NO_SHOW_SUSPEND_THRESHOLD = 3
INSTRUCTOR_BUFFER_MINUTES = 15


def _round_half_up_cents(value):
    """Round a Decimal value half-up to whole cents (integer)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _round_half_up_tenths(value):
    """Round a Decimal value half-up to one decimal place (tenths)."""
    return Decimal(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _d(x):
    """Decimal from a number, going through str to avoid float artifacts."""
    return Decimal(str(x))


def booking_cost_estimate(rental_rate_cents_per_hour, cfi_rate_cents_per_hour,
                          estimated_hours, is_complex, lesson_type):
    """booking_cost_estimate (PRD §3.7).

    round-then-sum: each rate*hours product rounds to whole cents BEFORE
    portions are summed; surcharge applies to the aircraft portion only.
    """
    hours = _d(estimated_hours)

    aircraft_portion = _round_half_up_cents(_d(rental_rate_cents_per_hour) * hours)

    if lesson_type == "DUAL":
        instructor_portion = _round_half_up_cents(_d(cfi_rate_cents_per_hour) * hours)
    else:  # SOLO
        instructor_portion = 0

    if not is_complex:
        surcharge_pct = Decimal("0.00")
    elif hours <= COMPLEX_TIER1_HOURS:
        surcharge_pct = COMPLEX_TIER1_PCT
    else:
        surcharge_pct = COMPLEX_TIER2_PCT

    surcharge = _round_half_up_cents(_d(aircraft_portion) * surcharge_pct)

    return aircraft_portion + surcharge + instructor_portion


def flight_charge(billing_basis, hobbs_start, hobbs_end, tach_start, tach_end,
                  rental_rate_cents_per_hour, cfi_rate_cents_per_hour, lesson_type):
    """flight_charge (PRD §3.7).

    Round the meter delta to tenths FIRST, then multiply by the rate, then
    round the product to whole cents. Returns
    (billed_hours: float, aircraft_charge_cents, instructor_charge_cents, total).
    """
    if billing_basis == "HOBBS":
        raw_delta = _d(hobbs_end) - _d(hobbs_start)
    else:  # TACH
        raw_delta = _d(tach_end) - _d(tach_start)

    billed_hours = _round_half_up_tenths(raw_delta)

    aircraft_charge = _round_half_up_cents(_d(rental_rate_cents_per_hour) * billed_hours)

    if lesson_type == "DUAL":
        instructor_charge = _round_half_up_cents(_d(cfi_rate_cents_per_hour) * billed_hours)
    else:
        instructor_charge = 0

    total = aircraft_charge + instructor_charge

    return float(billed_hours), aircraft_charge, instructor_charge, total
