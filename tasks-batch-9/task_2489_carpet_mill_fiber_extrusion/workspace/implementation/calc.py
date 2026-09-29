"""Pinned constants and pure calculations (SCAFFOLD calculations, PRD 2.5 / 3.x).

All rounding is round-half-up (never Python's banker's ``round``).  Money is
integer cents computed with :class:`decimal.Decimal`.
"""

import math
from decimal import Decimal, ROUND_HALF_UP

# ---- reclamation ----------------------------------------------------------
LB_TO_KG = 0.45359237
DEPOLYMERIZATION_YIELD = 0.82
MAX_RECLAIM_CONTAMINATION_PCT = 12.0
FACE_FIBER_FRACTION = {
    "NYLON_66": 0.42,
    "NYLON_6": 0.40,
    "PET": 0.38,
    "POLYPROPYLENE": 0.35,
}

# ---- extrusion ------------------------------------------------------------
DENIER_TOLERANCE_FRACTION = Decimal("0.03")
MIN_MELT_FLOW_INDEX = Decimal("12.0")
SPIN_YIELD = 0.965

# ---- tufting / face weight ------------------------------------------------
GAUGE_NEEDLES_PER_INCH = {"G_1_8": 8.0, "G_1_10": 10.0, "G_5_64": 12.8}
SQ_IN_PER_SQ_YD = 1296
MM_PER_INCH = 25.4
CUT_PILE_ALLOWANCE_IN = 0.0600
LOOP_PILE_ALLOWANCE_IN = 0.1200
GRAMS_PER_YARD_PER_DENIER = 0.00010160
GRAMS_PER_OZ = 28.349523
FACE_WEIGHT_TOLERANCE_OZ = Decimal("1.60")
PILE_HEIGHT_SPEC_TOLERANCE_MM = Decimal("0.5")

# ---- backing --------------------------------------------------------------
SBR_COEFF_PER_PCT = 0.0500
FILLER_PENALTY_PER_PCT = 0.0200
REFERENCE_CURE_SECONDS = 120.0
SECONDARY_BACKING_FACTOR = {
    "ACTION_BAC": 1.00,
    "WOVEN_POLYPROPYLENE": 0.95,
    "CUSHION": 1.10,
}
MIN_DELAMINATION_LBF = Decimal("2.50")
RECOAT_LIMIT = 1

# ---- shade ----------------------------------------------------------------
SHADE_BAND_A_MAX = Decimal("0.80")
SHADE_BAND_B_MAX = Decimal("1.50")
SHADE_BAND_C_MAX = Decimal("2.50")
MAX_REDYE_COUNT = 2

# ---- product testing ------------------------------------------------------
WEAR_TARR_MIN = Decimal("3.0")
STAIN_AATCC175_MIN = Decimal("8.0")
FLAMMABILITY_CHAR_MAX_MM = Decimal("25.4")

# ---- recycled content -----------------------------------------------------
NSF_140_MIN_RECYCLED_PCT = Decimal("25.00")

# ---- ordering / inventory -------------------------------------------------
STYLE_BACKORDER_ALERT_YARDS = Decimal("250")
REMNANT_THRESHOLD_YARDS = Decimal("30.0")

# ---- pricing --------------------------------------------------------------
SHADE_BAND_PRICE_FACTOR = {
    "A": Decimal("1.00"),
    "B": Decimal("0.97"),
    "C": Decimal("0.90"),
    "OUT": Decimal("0.00"),
    "SOLUTION": Decimal("1.00"),
}
REMNANT_LINE_DISCOUNT_PCT = Decimal("0.15")
FREIGHT_ALLOWED_MIN_CENTS = 100000
FREIGHT_MID_MIN_CENTS = 50000
FREIGHT_MID_CENTS = 4500
FREIGHT_BASE_CENTS = 8900
REMNANT_ORDER_CREDIT_PCT = Decimal("0.03")


# ---- rounding helpers -----------------------------------------------------

def dec(value):
    """Exact Decimal for a stored value (all stored numbers are fixed-scale)."""
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal(0)
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(repr(float(value)))


def rhu(value, places):
    """Round half up to ``places`` decimals, returning a Decimal."""
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def num(value, places):
    """Round half up and hand back a JSON-friendly float."""
    return float(rhu(value, places))


def cents(value):
    return int(rhu(value, 0))


# ---- calculation 1: reclamation yield ------------------------------------

def reclamation_yield_kg(intake_lbs, face_fiber_type):
    fraction = FACE_FIBER_FRACTION[face_fiber_type]
    raw = float(intake_lbs) * LB_TO_KG * fraction * DEPOLYMERIZATION_YIELD
    return num(raw, 3)


# ---- calculation 3: denier / drawn mass ----------------------------------

def denier_actual(throughput_g_per_min, spin_speed_m_per_min, filament_count):
    raw = float(throughput_g_per_min) * 9000.0 / (
        float(spin_speed_m_per_min) * float(filament_count)
    )
    return num(raw, 1)


def extruded_kg(input_kg, blend_input_kg):
    raw = (float(input_kg) + float(blend_input_kg or 0.0)) * SPIN_YIELD
    return num(raw, 3)


def denier_within_tolerance(actual, target):
    return abs(dec(actual) - dec(target)) <= dec(target) * DENIER_TOLERANCE_FRACTION


# ---- calculation 4: face weight per square yard --------------------------

def face_weight_oz_per_sy(
    gauge_code, stitch_rate_per_inch, pile_height_set_mm, pile_construction,
    denier, plies,
):
    npi = GAUGE_NEEDLES_PER_INCH[gauge_code]
    tufts_per_sy = npi * float(stitch_rate_per_inch) * SQ_IN_PER_SQ_YD
    allowance_in = (
        CUT_PILE_ALLOWANCE_IN if pile_construction == "CUT" else LOOP_PILE_ALLOWANCE_IN
    )
    yarn_in_per_tuft = 2.0 * (float(pile_height_set_mm) / MM_PER_INCH) + allowance_in
    yarn_yd_per_sy = tufts_per_sy * yarn_in_per_tuft / 36.0
    grams_per_sy = (
        yarn_yd_per_sy * float(denier) * float(plies) * GRAMS_PER_YARD_PER_DENIER
    )
    return num(grams_per_sy / GRAMS_PER_OZ, 2)


def face_weight_within_tolerance(actual, target):
    return abs(dec(actual) - dec(target)) <= FACE_WEIGHT_TOLERANCE_OZ


# ---- calculation 5: delamination strength --------------------------------

def delamination_strength_lbf(
    sbr_pct, filler_load_pct, cure_seconds, cure_temp_c, secondary_backing_type
):
    base = SBR_COEFF_PER_PCT * float(sbr_pct) - FILLER_PENALTY_PER_PCT * float(
        filler_load_pct
    )
    cure_index = min(1.00, float(cure_seconds) / REFERENCE_CURE_SECONDS)
    temp = int(cure_temp_c)
    if temp >= 150:
        temp_factor = 1.00
    elif temp >= 135:
        temp_factor = 0.88
    else:
        temp_factor = 0.70
    backing_factor = SECONDARY_BACKING_FACTOR[secondary_backing_type]
    return num(base * cure_index * temp_factor * backing_factor, 2)


def delamination_passes(strength):
    return dec(strength) >= MIN_DELAMINATION_LBF


# ---- calculation 7: colour difference and shade band ---------------------

def delta_e_cie76(target_l, target_a, target_b, measured_l, measured_a, measured_b):
    raw = math.sqrt(
        (float(measured_l) - float(target_l)) ** 2
        + (float(measured_a) - float(target_a)) ** 2
        + (float(measured_b) - float(target_b)) ** 2
    )
    return num(raw, 2)


def shade_band_for(delta_e):
    value = dec(delta_e)
    if value <= SHADE_BAND_A_MAX:
        return "A"
    if value <= SHADE_BAND_B_MAX:
        return "B"
    if value <= SHADE_BAND_C_MAX:
        return "C"
    return "OUT"


# ---- calculation 8: product test verdict ---------------------------------

def product_test_verdict(test_type, result_value):
    value = dec(result_value)
    if test_type == "WEAR_TARR":
        return "PASS" if value >= WEAR_TARR_MIN else "FAIL"
    if test_type == "STAIN_AATCC175":
        return "PASS" if value >= STAIN_AATCC175_MIN else "FAIL"
    if test_type == "FLAMMABILITY_PILL":
        return "PASS" if value <= FLAMMABILITY_CHAR_MAX_MM else "FAIL"
    return "FAIL"


# ---- calculation 17: per-line charge -------------------------------------

def line_cents(yards, list_price_cents_per_yard, shade_band, from_remnant):
    band_factor = SHADE_BAND_PRICE_FACTOR.get(shade_band, Decimal("1.00"))
    remnant_factor = (
        Decimal("1.00") - REMNANT_LINE_DISCOUNT_PCT if from_remnant else Decimal("1.00")
    )
    raw = dec(yards) * Decimal(int(list_price_cents_per_yard)) * band_factor * remnant_factor
    return cents(raw)


def freight_cents_for(gross_cents):
    if gross_cents >= FREIGHT_ALLOWED_MIN_CENTS:
        return 0
    if gross_cents >= FREIGHT_MID_MIN_CENTS:
        return FREIGHT_MID_CENTS
    return FREIGHT_BASE_CENTS


def remnant_credit_cents_for(gross_cents):
    return cents(Decimal(int(gross_cents)) * REMNANT_ORDER_CREDIT_PCT)
