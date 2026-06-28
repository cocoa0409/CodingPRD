"""Calculation rules (scaffold §1.3, PRD §2.7 / §3.4 / §3.7).

All money is integer cents. Per-line monetary amounts are rounded to the nearest
whole cent using round-half-up BEFORE summation (round-then-sum). Risk scores and
relocation distance are rounded to two decimal places using round-half-up.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

# Constants (scaffold §1.3)
EMERGENCY_SURCHARGE_PCT = Decimal("0.15")
REGULATED_MULTIPLIER = Decimal("1.5")
RISK_SCORE_CAP = Decimal("1000.0")
EARTH_RADIUS_MILES = 3958.8
SANITATION_FEE_CENTS = 7500
WARRANTY_DAYS = 30
TRAP_VISIT_BUFFER_MINUTES = 15

SEVERITY_FACTOR = {
    "MINOR": Decimal("1.0"),
    "MODERATE": Decimal("2.0"),
    "MAJOR": Decimal("3.5"),
}


def _round_half_up_to_int(value):
    """Round a Decimal to the nearest whole integer using round-half-up."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _round_half_up_2dp(value):
    """Round a Decimal to 2 decimal places using round-half-up; return float."""
    q = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(q)


def surcharge_factor(emergency_flag):
    """1 + 15% when emergency, exactly 1 otherwise (PRD §2.7 / §3.3)."""
    if emergency_flag:
        return Decimal("1") + EMERGENCY_SURCHARGE_PCT
    return Decimal("1")


def line_amount_cents(line, factor):
    """Per-line raw = quantity * unit_price_cents * surcharge, rounded to the cent."""
    raw = Decimal(line["quantity"]) * Decimal(line["unit_price_cents"]) * factor
    return _round_half_up_to_int(raw)


def quote_provisional_total(line_items, emergency_flag):
    """Round-then-sum over ALL line items (scaffold calc quote_provisional_total)."""
    factor = surcharge_factor(emergency_flag)
    total = 0
    for li in line_items:
        total += line_amount_cents(li, factor)
    return total


def quote_final_total(line_items, emergency_flag):
    """Round-then-sum over only performed line items (calc quote_final_total)."""
    factor = surcharge_factor(emergency_flag)
    total = 0
    for li in line_items:
        if li.get("performed"):
            total += line_amount_cents(li, factor)
    return total


def performed_subtotal(line_items, completed_sanitation_repair_count, emergency_flag):
    """Performed lines round-then-sum + flat sanitation fee per sanitation repair.

    calc workorder_net_charge (PRD §3.7).
    """
    subtotal = quote_final_total(line_items, emergency_flag)
    subtotal += SANITATION_FEE_CENTS * completed_sanitation_repair_count
    return subtotal


def infestation_risk_score(entry_points, species_by_id):
    """Weighted scoring with severity multiplier, regulated bump, global cap.

    entry_points: the variant's input set (caller supplies initial vs residual set).
    """
    score = Decimal("0")
    for ep in entry_points:
        sp = species_by_id(ep["species_id"])
        base = (
            Decimal(ep["estimated_individuals"])
            * _to_decimal(sp["risk_weight"])
            * SEVERITY_FACTOR[ep["severity"]]
        )
        if sp.get("is_regulated"):
            base = base * REGULATED_MULTIPLIER
        score += base
    if score > RISK_SCORE_CAP:
        score = RISK_SCORE_CAP
    return _round_half_up_2dp(score)


def haversine_miles(lat1, lon1, lat2, lon2):
    """Great-circle distance in miles (Earth radius 3958.8 mi)."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_MILES * c


def relocation_distance_miles(prop_lat, prop_lon, rel_lat, rel_lon):
    d = haversine_miles(prop_lat, prop_lon, rel_lat, rel_lon)
    return _round_half_up_2dp(_to_decimal(d))


def _to_decimal(v):
    return Decimal(str(v))
