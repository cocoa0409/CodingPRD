"""Calculation rules (PRD 2.8, 2.9, 3.2, 3.6, 3.8, 3.9; scaffold 1.3).

All computed quantities that are not exact literals are rounded to two decimal
places using round-half-up. Monetary amounts are whole integer cents; dose-unit
counts are whole integers obtained by ceiling.
"""

import math
from decimal import Decimal, ROUND_HALF_UP

# --- 2.9 Concentration tiers, vial colors, build-up ladder -------------------
COLORS = ["GREEN", "YELLOW", "RED", "SILVER"]

DILUTION_BY_COLOR = {
    "GREEN": Decimal("0.001"),
    "YELLOW": Decimal("0.01"),
    "RED": Decimal("0.1"),
    "SILVER": Decimal("1.0"),
}

SHELF_LIFE_DAYS = {
    "GREEN": 30,
    "YELLOW": 90,
    "RED": 180,
    "SILVER": 365,
}

# Build-up ladder step volumes in mL (PRD 3.6 / scaffold dosing_schedule).
BUILD_UP_STEPS = {
    "GREEN": [Decimal("0.10"), Decimal("0.20"), Decimal("0.40")],
    "YELLOW": [Decimal("0.10"), Decimal("0.20"), Decimal("0.40")],
    "RED": [Decimal("0.10"), Decimal("0.20"), Decimal("0.30"), Decimal("0.40")],
    "SILVER": [Decimal("0.10"), Decimal("0.20"), Decimal("0.30"), Decimal("0.40"), Decimal("0.50")],
}

MAINTENANCE_TOP_VOLUME_ML = Decimal("0.50")

# Next/previous color in the ladder.
NEXT_COLOR = {"GREEN": "YELLOW", "YELLOW": "RED", "RED": "SILVER", "SILVER": "SILVER"}
PREV_COLOR = {"SILVER": "RED", "RED": "YELLOW", "YELLOW": "GREEN", "GREEN": "GREEN"}

# Tier -> starting vial color (PRD 3.3).
TIER_TO_COLOR = {"HIGH": "GREEN", "MODERATE": "YELLOW", "LOW": "RED"}

# IgE class boundaries in kU/L (PRD 3.2 / scaffold panel_sensitization_score).
IGE_CLASS_BOUNDS_KU = [0.35, 0.70, 3.5, 17.5, 50, 100]

SKIN_POSITIVE_DIFF_MM = 3
TIER_MODERATE_FLOOR = 4
TIER_HIGH_FLOOR = 7

REDUCTION_PCT = Decimal("0.25")

OBS_STANDARD_MIN = 30
OBS_EXTENDED_MIN = 45

# Billing constants (PRD 3.9 / scaffold billing_charge).
PRICE_95115_CENTS = 2600
PRICE_95117_CENTS = 3900
PRICE_95165_PER_DOSE_CENTS = 1450
DOSE_CAP = 10


def round2(value):
    """Round to two decimal places, half-up. Returns a float."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _to_decimal(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


# --- AllergenTest scoring (PRD 3.2) ------------------------------------------

def ige_class(specific_ige_ku):
    """Map specific IgE (kU/L) to an IgE class on a 0..6 scale (PRD 3.2)."""
    ku = specific_ige_ku
    if ku < 0.35:
        return 0
    if ku < 0.70:
        return 1
    if ku < 3.5:
        return 2
    if ku < 17.5:
        return 3
    if ku < 50:
        return 4
    if ku < 100:
        return 5
    return 6


def score_test(method, wheal_mm, specific_ige_ku, control_wheal_mm):
    """Return (sensitization_index, is_positive) for an allergen test."""
    if method == "SKIN":
        diff = wheal_mm - control_wheal_mm
        sensitization_index = max(0, diff)
        is_positive = diff >= SKIN_POSITIVE_DIFF_MM
        return sensitization_index, is_positive
    # BLOOD
    cls = ige_class(specific_ige_ku)
    return cls, cls >= 1


def compute_composites(tests):
    """Compute (screening_composite, clinical_composite, recommended_tier).

    SCREENING: mean sensitization_index over ALL tests.
    CLINICAL: mean over tests with clinically_relevant=true; 0 when none.
    Both rounded 2dp half-up. Tier derived from clinical_composite.
    """
    if not tests:
        screening = 0.0
    else:
        total = sum(_to_decimal(t["sensitization_index"]) for t in tests)
        screening = round2(total / Decimal(len(tests)))

    clinical_tests = [t for t in tests if t.get("clinically_relevant")]
    if not clinical_tests:
        clinical = 0.0
    else:
        total = sum(_to_decimal(t["sensitization_index"]) for t in clinical_tests)
        clinical = round2(total / Decimal(len(clinical_tests)))

    if clinical < TIER_MODERATE_FLOOR:
        tier = "LOW"
    elif clinical < TIER_HIGH_FLOOR:
        tier = "MODERATE"
    else:
        tier = "HIGH"
    return screening, clinical, tier


# --- Dosing schedule (PRD 3.6) -----------------------------------------------

def scheduled_dose(color, step_index, phase):
    """Volume the schedule prescribes for the given ladder position (mL).

    While MAINTENANCE, the dose is fixed at the maintenance top volume.
    Returns a float (2dp literal).
    """
    if phase == "MAINTENANCE":
        return float(MAINTENANCE_TOP_VOLUME_ML)
    steps = BUILD_UP_STEPS[color]
    return float(steps[step_index - 1])


def advance_ladder(plan):
    """Advance the plan one build-up step on RELEASE (PRD 3.6).

    Mutates current_step_index / current_vial_color / phase in place.
    """
    color = plan["current_vial_color"]
    steps = BUILD_UP_STEPS[color]
    if plan["current_step_index"] < len(steps):
        plan["current_step_index"] += 1
    else:
        next_color = NEXT_COLOR[color]
        if next_color == color and color == "SILVER":
            # Already at SILVER top step and that step released -> MAINTENANCE.
            plan["phase"] = "MAINTENANCE"
        else:
            plan["current_vial_color"] = next_color
            plan["current_step_index"] = 1


def step_back_ladder(plan):
    """Step the ladder back one rung (PRD 3.8 systemic re-entry).

    Mutates current_step_index / current_vial_color in place. GREEN floors.
    """
    if plan["current_step_index"] > 1:
        plan["current_step_index"] -= 1
    else:
        prev = PREV_COLOR[plan["current_vial_color"]]
        plan["current_vial_color"] = prev
        plan["current_step_index"] = 1


def reduced_reentry_volume(last_dose_volume_ml):
    """75% of the last administered volume, 2dp half-up (PRD 3.8)."""
    reduced = _to_decimal(last_dose_volume_ml) * (Decimal("1") - REDUCTION_PCT)
    return round2(reduced)


# --- Antigen units (PRD 3.6) -------------------------------------------------

def antigen_units(administered_volume_ml, color, potency_pnu_per_ml):
    """administered_volume * dilution_factor * potency, rounded ONCE half-up 2dp."""
    product = (
        _to_decimal(administered_volume_ml)
        * DILUTION_BY_COLOR[color]
        * _to_decimal(potency_pnu_per_ml)
    )
    return round2(product)


# --- Observation window (PRD 3.6) --------------------------------------------

def observation_window(prior_systemic_reaction, scheduled_step_volume, last_dose_volume_ml):
    """30 standard; 45 extended when prior_systemic_reaction or dose escalated."""
    escalated = _to_decimal(scheduled_step_volume) > _to_decimal(last_dose_volume_ml)
    if prior_systemic_reaction or escalated:
        return OBS_EXTENDED_MIN
    return OBS_STANDARD_MIN


# --- Billing (PRD 3.9) -------------------------------------------------------

def dose_units_from_volume_ml(volume_ml):
    """Ceiling of millilitres, capped at DOSE_CAP (PRD 3.9 / 2.8)."""
    units = math.ceil(_to_decimal(volume_ml))
    return min(units, DOSE_CAP)


def provisional_95165_units(prepared_volume_ml):
    return dose_units_from_volume_ml(prepared_volume_ml)


def final_95165_units(sum_administered_ml):
    return dose_units_from_volume_ml(sum_administered_ml)


def injection_charge(injection_count):
    """Return (cpt_code, charge_cents) for the per-visit injection code."""
    if injection_count >= 2:
        return "CPT_95117", PRICE_95117_CENTS
    return "CPT_95115", PRICE_95115_CENTS
