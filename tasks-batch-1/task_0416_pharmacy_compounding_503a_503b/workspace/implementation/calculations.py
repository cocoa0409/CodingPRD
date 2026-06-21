"""Calculation rules (PRD §3, SCAFFOLD §1.3).

All money/precision-sensitive math uses decimal.Decimal with ROUND_HALF_UP.
Datetime arithmetic in whole days. Floats are used only where the PRD explicitly
calls for full floating-point precision (endotoxin projection).
"""
from decimal import Decimal, ROUND_HALF_UP

import timeutil

# --- Constants (SCAFFOLD §1.3) ---
STERILE_AQUEOUS_BUD_DAYS = 14
STERILE_NONAQUEOUS_BUD_DAYS = 45
OFFICE_USE_BUD_CAP_DAYS = 90
YIELD_TOLERANCE_PCT = Decimal("5.0")
INJECTABLE_EU_LIMIT = 175
NONINJECTABLE_EU_LIMIT = 350
PRESCRIPTION_VALIDITY_DAYS = 180

STERILE_FORMS = {"STERILE_AQUEOUS", "STERILE_NONAQUEOUS"}


def round_half_up(value, places):
    """Round a numeric value to `places` decimals using ROUND_HALF_UP, return float."""
    q = Decimal(1).scaleb(-places)  # 10^-places
    d = Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)
    return float(d)


def potency_adjusted_grams(grams_used, labeled_potency_pct):
    """= round(grams_used * (labeled_potency_pct / 100), 4)  [round_half_up]"""
    val = Decimal(str(grams_used)) * (Decimal(str(labeled_potency_pct)) / Decimal("100"))
    return float(val.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def remaining_grams(initial_grams, used_total):
    """= initial_grams - used_total, carried to 4 decimals."""
    val = Decimal(str(initial_grams)) - Decimal(str(used_total))
    return float(val.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def yield_variance_pct(actual_yield_units, theoretical_yield_units):
    """= round(100 * (actual - theoretical) / theoretical, 2)  [round_half_up]."""
    val = (Decimal("100") * (Decimal(str(actual_yield_units)) - Decimal(str(theoretical_yield_units)))
           / Decimal(str(theoretical_yield_units)))
    return float(val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def yield_within_tolerance(variance_pct):
    """Variance from -5.00 through +5.00 inclusive is acceptable."""
    v = Decimal(str(variance_pct))
    return (-YIELD_TOLERANCE_PCT) <= v <= YIELD_TOLERANCE_PCT


def base_bud_days(is_sterile, dosage_form, default_bud_days_nonsterile):
    if is_sterile:
        if dosage_form == "STERILE_AQUEOUS":
            return STERILE_AQUEOUS_BUD_DAYS
        return STERILE_NONAQUEOUS_BUD_DAYS
    return default_bud_days_nonsterile


def assigned_bud_utc(current_utc_dt, purpose, base_days, earliest_lot_expiry_dt):
    """Compute the beyond-use datetime (PRD §3.6).

    503B OFFICE_USE caps the base window at 90 days BEFORE the ingredient-expiry
    floor. The ingredient-expiry floor is then min(candidate, earliest_lot_expiry);
    ties favor the ingredient expiry.
    """
    chosen_days = base_days
    if purpose == "OFFICE_USE":
        chosen_days = min(base_days, OFFICE_USE_BUD_CAP_DAYS)
    candidate = timeutil.add_days(current_utc_dt, chosen_days)
    if earliest_lot_expiry_dt is not None and earliest_lot_expiry_dt <= candidate:
        # Tie favors the ingredient expiry.
        return earliest_lot_expiry_dt
    return candidate


def endotoxin_projection(measured_value, total_active_mg, theoretical_yield_units):
    """projected_eu_per_unit = measured_value * (total_active_mg / theoretical_yield_units).

    Full floating-point precision (PRD §3.7).
    """
    return float(measured_value) * (float(total_active_mg) / float(theoretical_yield_units))


def endotoxin_limit(dosage_form):
    return INJECTABLE_EU_LIMIT if dosage_form == "STERILE_AQUEOUS" else NONINJECTABLE_EU_LIMIT
