"""Settlement, cancellation-refund and mechanical-refund calculations.

Pinned rounding order (PRD §2.7): every line is rounded half-up to whole
cents FIRST; totals are plain sums of the rounded lines. Fuel gallons are
rounded half-up to one decimal place before being priced.
"""

import math
from datetime import datetime, time, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

import db

FUEL_PRICE_CENTS_PER_GALLON = 700
PUMP_OUT_FEE_CENTS = 15000
CLEANING_FEE_CENTS = 25000
LATE_HOURLY_CENTS = 5000
ESTIMATED_BURN_PCT = 50

GROUNDING_BASE = {
    "MINOR": 50000,
    "MAJOR": 250000,
    "TOTAL_LOSS": 900000,
}

TIER_FULL_DAYS = 30
TIER_HALF_DAYS = 14
TIER_QUARTER_DAYS = 8
PCT_FULL = 90
PCT_HALF = 50
PCT_QUARTER = 25


def _round_cents(value):
    """Round a Decimal/Rational-like to whole cents, half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_gallons(numerator, denominator=100):
    """Round half up to one decimal place."""
    val = Decimal(numerator) / Decimal(denominator)
    return val.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# settlement_total — PROVISIONAL and FINAL variants
# ---------------------------------------------------------------------------

def provisional_estimate(vessel):
    """PROVISIONAL variant computed at checkout: 50% burn fuel estimate,
    pump-out assumed due, cleaning fee included, everything else zero."""
    gallons = round_gallons(ESTIMATED_BURN_PCT * vessel["fuel_tank_capacity_gallons"], 100)
    fuel_cents = int(gallons * FUEL_PRICE_CENTS_PER_GALLON)
    return fuel_cents + PUMP_OUT_FEE_CENTS + CLEANING_FEE_CENTS


def return_deadline(end_date):
    return datetime.combine(end_date, time(10, 0, 0), tzinfo=timezone.utc)


def final_operational_lines(booking, vessel):
    """FINAL-variant operational lines: list of (line_type, amount_cents).
    Each line computed and rounded to whole cents first."""
    # FUEL: gauge delta floored at zero; gallons half-up to 1 decimal.
    delta_pct = max(
        0,
        booking["checkout_fuel_gauge_percent"] - booking["return_fuel_gauge_percent"],
    )
    gallons = round_gallons(delta_pct * vessel["fuel_tank_capacity_gallons"], 100)
    fuel_cents = int(gallons * FUEL_PRICE_CENTS_PER_GALLON)

    # PUMP_OUT: due when pumped at checkout but not at return.
    pump_out_cents = (
        PUMP_OUT_FEE_CENTS
        if booking["checkout_pump_out_done"] and not booking["return_pump_out_done"]
        else 0
    )

    # CLEANING_FEE: always.
    cleaning_cents = CLEANING_FEE_CENTS

    # LATE_RETURN: deadline 10:00:00Z on end_date; excess rounded up to hours.
    late_cents = 0
    actual = booking["actual_return_at"]
    if actual is not None and actual > return_deadline(booking["end_date"]):
        excess_seconds = (actual - return_deadline(booking["end_date"])).total_seconds()
        late_hours = math.ceil(excess_seconds / 3600)
        late_cents = late_hours * LATE_HOURLY_CENTS

    return [
        ("FUEL", fuel_cents),
        ("PUMP_OUT", pump_out_cents),
        ("CLEANING_FEE", cleaning_cents),
        ("LATE_RETURN", late_cents),
    ]


# ---------------------------------------------------------------------------
# cancellation_refund — STANDARD tiers / WEATHER override / SYSTEM 100%
# ---------------------------------------------------------------------------

def approved_itinerary(booking_id):
    for it in db.all_of("itineraries"):
        if it["booking_id"] == booking_id and it["status"] == "APPROVED":
            return it
    return None


def _dt_of_date(d):
    return datetime.combine(d, time(0, 0, 0), tzinfo=timezone.utc)


def weather_variant_applies(booking):
    """True when an ACTIVE advisory's half-open window overlaps the stay
    (window_start < end_date AND window_end > start_date) and its zone_ids
    intersect the APPROVED itinerary's waypoint zones."""
    itin = approved_itinerary(booking["id"])
    if itin is None:
        return False
    zones = {w["zone_id"] for w in itin["waypoints"]}
    if not zones:
        return False
    stay_start = _dt_of_date(booking["start_date"])
    stay_end = _dt_of_date(booking["end_date"])
    for a in db.all_of("weather_advisories"):
        if a["status"] != "ACTIVE":
            continue
        if a["window_start"] < stay_end and a["window_end"] > stay_start:
            if zones.intersection(a["zone_ids"]):
                return True
    return False


def cancellation_refund_pct(booking, system_reason):
    """Return (pct, applied_weather). HELD -> 0%. System reasons -> 100%.
    CONFIRMED renter-initiated: WEATHER override 100%, else STANDARD tiers."""
    if booking["status"] == "HELD":
        return 0, False
    if system_reason is not None:
        return 100, False
    if weather_variant_applies(booking):
        return 100, True
    days_before = (booking["start_date"] - db.current_date()).days
    if days_before >= TIER_FULL_DAYS:
        return PCT_FULL, False
    if days_before >= TIER_HALF_DAYS:
        return PCT_HALF, False
    if days_before >= TIER_QUARTER_DAYS:
        return PCT_QUARTER, False
    return 0, False


def cancellation_refund_cents(quoted_total_cents, pct):
    return _round_cents(Decimal(quoted_total_cents) * Decimal(pct) / Decimal(100))


# ---------------------------------------------------------------------------
# mechanical_prorated_refund
# ---------------------------------------------------------------------------

def mechanical_refund_cents(booking, unused_nights):
    """round_half_up(quoted_total_cents * unused_nights / total_nights)."""
    if booking["total_nights"] <= 0:
        return 0
    raw = Decimal(booking["quoted_total_cents"]) * Decimal(unused_nights) / Decimal(
        booking["total_nights"]
    )
    return _round_cents(raw)


def remaining_nights(booking):
    """Full nights from the current date to end_date (interrupt day is used)."""
    return (booking["end_date"] - db.current_date()).days
