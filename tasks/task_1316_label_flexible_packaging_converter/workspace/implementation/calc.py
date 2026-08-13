"""Pricing and material calculations (scaffold calculations table, PRD 3.4/3.5/3.7).

All arithmetic is exact rational math (fractions.Fraction); every computed
charge component is rounded UP to the next whole cent/foot (PRD 2.7).
"""
import math
from fractions import Fraction

# Unit conversions (PRD 2.7)
MM_PER_FT = Fraction(1524, 5)  # 304.8 mm per foot
MM_PER_IN = Fraction(127, 5)   # 25.4 mm per inch
IN_PER_FT = 12                 # 12 inches per foot

# job_material_calc constants
SHORT_RUN_THRESHOLD_FT = 5000

# Tier table (average-rate pricing, keyed on the FULL quantity)
RATE_A_CENTS_PER_K = 4500   # qty < 5000
RATE_B_CENTS_PER_K = 3800   # 5000 <= qty < 20000
RATE_C_CENTS_PER_K = 3200   # qty >= 20000
TIER_B_MIN = 5000
TIER_C_MIN = 20000

MIN_ORDER_QTY = 1000
NEW_DIE_CHARGE_CENTS = 750000
DELTA_E_PASS_MAX = 2.0

# Ink allowance: 1 lb per 5000 linear feet per station.
INK_FEET_PER_LB = 5000


def tier_rate(quantity):
    """Single average rate covering the entire quantity (NOT marginal)."""
    if quantity < TIER_B_MIN:
        return RATE_A_CENTS_PER_K
    if quantity < TIER_C_MIN:
        return RATE_B_CENTS_PER_K
    return RATE_C_CENTS_PER_K


def running_ft(quantity, repeat_length_mm):
    """ceil(quantity * repeat_length_mm / 304.8) — mm to feet, rounded up."""
    return math.ceil(Fraction(quantity * repeat_length_mm, 1) / MM_PER_FT)


def run_waste_ft(running, run_waste_pct_numerator):
    """ceil(running_ft * pct_numerator / 100) — running waste, whole feet."""
    return math.ceil(Fraction(running * run_waste_pct_numerator, 100))


def job_material_calc(quantity, repeat_length_mm, press):
    """material_ft frozen at release (scaffold job_material_calc).

    Setup waste is charged only when running footage is below the short-run
    threshold; on long runs makeready is amortized.
    """
    running = running_ft(quantity, repeat_length_mm)
    setup = press["setup_waste_ft"] if running < SHORT_RUN_THRESHOLD_FT else 0
    return running + setup + run_waste_ft(running, press["run_waste_pct_numerator"])


def _material_cents(feet, substrate):
    """MSI conversion: ft * 12 in/ft * (width_mm / 25.4) in / 1000, then cost."""
    msq = Fraction(feet * IN_PER_FT * substrate["width_mm"], 1) / MM_PER_IN / 1000
    return math.ceil(msq * substrate["cost_per_msq_cents"])


def _ink_cents(feet, color_count, ink_recipe):
    ink_lb = Fraction(feet * color_count, INK_FEET_PER_LB)
    return math.ceil(ink_lb * ink_recipe["cost_per_lb_cents"])


def job_quote_calc(quantity, repeat_length_mm, press, substrate, ink_recipe, artwork):
    """Provisional quote at job creation (scaffold job_quote_calc).

    Keyed on quantity_ordered; includes setup waste unconditionally (worst
    case); excludes the new-die charge.
    """
    base_cents = math.ceil(Fraction(quantity * tier_rate(quantity), 1000))
    provisional_running = running_ft(quantity, repeat_length_mm)
    provisional_ft = (
        provisional_running
        + press["setup_waste_ft"]
        + run_waste_ft(provisional_running, press["run_waste_pct_numerator"])
    )
    material_cents = _material_cents(provisional_ft, substrate)
    ink_cents = _ink_cents(provisional_ft, artwork["color_count"], ink_recipe)
    return base_cents + material_cents + ink_cents + artwork["plate_set_cost_cents"]


def job_invoice_calc(job, substrate, ink_recipe, artwork):
    """Final invoice at ship (scaffold job_invoice_calc).

    Keyed on good_quantity_produced; uses the material_ft frozen at release;
    adds the die charge billed at release.
    """
    good = job["good_quantity_produced"]
    base_cents = math.ceil(Fraction(good * tier_rate(good), 1000))
    material_cents = _material_cents(job["material_ft"], substrate)
    ink_cents = _ink_cents(job["material_ft"], artwork["color_count"], ink_recipe)
    return (
        base_cents
        + material_cents
        + ink_cents
        + artwork["plate_set_cost_cents"]
        + job["die_charge_applied_cents"]
    )
