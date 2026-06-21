"""Precision-sensitive domain calculations.

All money/dose arithmetic uses decimal.Decimal with ROUND_HALF_UP.
"""
import math
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

GFR_CAP = 125


def _to_decimal(value):
    # Construct via str to avoid binary float artifacts.
    return Decimal(str(value))


def _round_half_up(value, places):
    quant = Decimal(1).scaleb(-places)  # 10^-places
    return _to_decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def bsa_mosteller(height_cm, weight_kg):
    """Mosteller BSA = round_half_up(sqrt(height_cm*weight_kg/3600), 2)."""
    product = _to_decimal(height_cm) * _to_decimal(weight_kg) / Decimal(3600)
    root = math.sqrt(float(product))
    return float(_round_half_up(root, 2))


def compute_dose(dosing_method, dose_per_m2, target_auc, flat_dose_mg,
                 bsa_snapshot, gfr_snapshot, vial_size_mg, dose_reduction_pct):
    """Compute ordered_dose_mg, vials_drawn, supplied_mg, waste_mg, jw_modifier.

    Order: base -> apply reduction on unrounded base -> round half-up to 0 dp.
    """
    r = _to_decimal(dose_reduction_pct)

    if dosing_method == "BSA":
        base = _to_decimal(dose_per_m2) * _to_decimal(bsa_snapshot)
    elif dosing_method == "AUC":
        capped_gfr = min(_to_decimal(gfr_snapshot), Decimal(GFR_CAP))
        base = _to_decimal(target_auc) * (capped_gfr + Decimal(25))
    else:  # FLAT
        base = _to_decimal(flat_dose_mg)

    reduced = base * (Decimal(1) - r / Decimal(100))
    ordered_dose_mg = int(_round_half_up(reduced, 0))

    vial = _to_decimal(vial_size_mg)
    # ceil(ordered_dose_mg / vial_size_mg)
    vials_drawn = int(math.ceil(Decimal(ordered_dose_mg) / vial))
    supplied_dec = Decimal(vials_drawn) * vial
    waste_dec = supplied_dec - Decimal(ordered_dose_mg)
    supplied_mg = _normalize_number(supplied_dec)
    waste_mg = _normalize_number(waste_dec)
    jw_modifier = waste_dec > 0

    return {
        "ordered_dose_mg": ordered_dose_mg,
        "vials_drawn": vials_drawn,
        "supplied_mg": supplied_mg,
        "waste_mg": waste_mg,
        "jw_modifier": jw_modifier,
    }


def _normalize_number(dec_value):
    """Return an int when the Decimal is integral, else a float."""
    if dec_value == dec_value.to_integral_value():
        return int(dec_value)
    return float(dec_value)


def scheduled_date(treatment_start_date, cycle_length_days, cycle_number, day_offset):
    """S + ((n-1)*L + (d-1)) days, calendar-day granularity."""
    start = date.fromisoformat(treatment_start_date)
    delta_days = (cycle_number - 1) * cycle_length_days + (day_offset - 1)
    result = start + timedelta(days=delta_days)
    return result.isoformat()
