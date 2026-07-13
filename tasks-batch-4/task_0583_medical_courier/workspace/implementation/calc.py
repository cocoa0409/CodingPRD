"""Calculation rules (SCAFFOLD 1.3 / PRD 2.6, 3.2, 3.4, 3.5, 3.7).

All monetary and scoring arithmetic runs through Decimal with ROUND_HALF_UP —
never float. Temperatures are compared to two decimal places, inclusively.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

# --- constants -------------------------------------------------------------
STAT_SLA_MIN = 120
SCHEDULED_SLA_MIN = 480

BASE_RISK = {"BLOOD": 10, "TISSUE": 20, "URINE": 5, "SWAB": 5, "CULTURE": 15}
EXCURSION_PENALTY = 25
TIME_DIVISOR_MIN = 10

SPECIMEN_TYPES = set(BASE_RISK)
TEMP_REQUIREMENTS = {"AMBIENT", "REFRIGERATED", "FROZEN"}
CREDENTIAL_TYPES = {"STANDARD", "BLOODBORNE", "HAZMAT"}
STOP_KINDS = {"PICKUP", "DROPOFF", "BOTH"}
RUN_TYPES = {"STAT", "SCHEDULED"}
CADENCES = {"DAILY", "WEEKDAYS", "WEEKLY"}


def D(v):
    """Exact Decimal from any numeric/str input (never binary float)."""
    if isinstance(v, Decimal):
        return v
    return Decimal(str(v))


def rhu(v):
    """Round half up to a whole integer."""
    return int(D(v).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- route_sla_deadline ----------------------------------------------------

def sla_deadline(scheduled_start, run_type):
    minutes = STAT_SLA_MIN if run_type == "STAT" else SCHEDULED_SLA_MIN
    return scheduled_start + timedelta(minutes=minutes)


# --- route_charge ----------------------------------------------------------

def _surcharge(base, run_type, rate_card):
    """STAT surcharge: round-half-up(base * pct), capped. Zero on SCHEDULED."""
    if run_type != "STAT":
        return 0
    raw = rhu(D(base) * D(rate_card["stat_surcharge_pct"]))
    return min(raw, rate_card["stat_surcharge_cap_cents"])


def provisional_charge(route, rate_card, stops, specimens):
    """Provisional variant (at dispatch): the whole-route mileage is rounded ONCE.

    Counts EVERY stop of the route (regardless of state) and EVERY specimen.
    """
    stop_subtotal = rate_card["per_stop_fee_cents"] * len(stops)
    mile_subtotal = rhu(D(route["planned_total_miles"]) * D(rate_card["per_mile_rate_cents"]))
    temp_count = sum(1 for s in specimens if s["temp_requirement"] != "AMBIENT")
    temp_subtotal = rate_card["temp_handling_fee_cents"] * temp_count
    base = stop_subtotal + mile_subtotal + temp_subtotal
    return base + _surcharge(base, route["run_type"], rate_card)


def leg_charge(actual_leg_miles, rate_card):
    """per_stop_fee + round_half_up(actual_leg_miles * per_mile_rate)."""
    miles = 0 if actual_leg_miles is None else actual_leg_miles
    return rate_card["per_stop_fee_cents"] + rhu(D(miles) * D(rate_card["per_mile_rate_cents"]))


def final_charge(route, rate_card, stops, specimens):
    """Final variant (at complete): each COMPLETED leg is rounded, THEN summed.

    MISSED stops are excluded; only DELIVERED temp-controlled specimens count.
    Returns (gross_base, surcharge, net).
    """
    completed = [s for s in stops if s["status"] == "COMPLETED"]
    completed.sort(key=lambda s: (s["sequence"], s["created_at"], s["_seq"]))
    leg_stop_subtotal = sum(
        s["leg_charge_cents"]
        if s["leg_charge_cents"] is not None
        else leg_charge(s["actual_leg_miles"], rate_card)
        for s in completed
    )
    temp_count_final = sum(
        1 for s in specimens
        if s["temp_requirement"] != "AMBIENT" and s["custody_status"] == "DELIVERED"
    )
    temp_subtotal_f = rate_card["temp_handling_fee_cents"] * temp_count_final
    base_f = leg_stop_subtotal + temp_subtotal_f
    surcharge_f = _surcharge(base_f, route["run_type"], rate_card)
    return base_f, surcharge_f, base_f + surcharge_f


# --- specimen_risk ---------------------------------------------------------

def _minutes_between(start, end):
    return D((end - start).total_seconds()) / D(60)


def estimated_risk(specimen, route):
    """At PICKUP: base + round_half_up(planned window minutes / 10)."""
    est_minutes = _minutes_between(route["scheduled_start"], route["scheduled_end"])
    return BASE_RISK[specimen["specimen_type"]] + rhu(est_minutes / D(TIME_DIVISOR_MIN))


def final_risk(specimen):
    """At DROPOFF: base + round_half_up(actual transit / 10) + 25 * excursion_count."""
    act_minutes = _minutes_between(specimen["picked_up_at"], specimen["delivered_at"])
    return (
        BASE_RISK[specimen["specimen_type"]]
        + rhu(act_minutes / D(TIME_DIVISOR_MIN))
        + specimen["excursion_count"] * EXCURSION_PENALTY
    )


# --- temperature_excursion_eval -------------------------------------------

_CENTI = Decimal("0.01")


def is_excursion(temp_reading_c, specimen):
    """Reading strictly outside the inclusive [min, max] band, to 2 decimal places."""
    reading = D(temp_reading_c).quantize(_CENTI, rounding=ROUND_HALF_UP)
    lo = D(specimen["required_temp_min_c"]).quantize(_CENTI, rounding=ROUND_HALF_UP)
    hi = D(specimen["required_temp_max_c"]).quantize(_CENTI, rounding=ROUND_HALF_UP)
    return reading < lo or reading > hi


# --- credential sufficiency (PRD 3.4) --------------------------------------

def credential_sufficient(credential_type, specimens):
    """CULTURE requires BLOODBORNE|HAZMAT; FROZEN requires HAZMAT."""
    for s in specimens:
        if s["specimen_type"] == "CULTURE" and credential_type not in ("BLOODBORNE", "HAZMAT"):
            return False
        if s["temp_requirement"] == "FROZEN" and credential_type != "HAZMAT":
            return False
    return True
