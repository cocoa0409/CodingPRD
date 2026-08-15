"""Calculation rules (scaffold table 3 / PRD 3.3, 3.5): pricing, freight, tolerances.

All monetary values are integer cents. Lines are rounded half-up individually
and only then summed (PRD 2.9); summing unrounded lines is non-conformant.
"""
from decimal import Decimal, ROUND_HALF_UP

# component_line_total: action-tier labor rates in cents per hour.
LABOR_RATE_CENTS = {
    "REGRIND": 8500,
    "CUT_NEW": 14200,
    "REPLACE_OEM": 6000,   # labor only; the part cost rides on material_cents
    "REUSE_AS_IS": 2500,
}
RUSH_MULTIPLIER = Decimal("1.25")

# freight_charge constants.
RIGGING_HOURLY_CENTS = 9500
RIGGING_BUFFER_HOURS = 2

# assembly_tolerance constants (inclusive backlash band, inclusive clearance cap).
BACKLASH_MIN = Decimal("0.08")
BACKLASH_MAX = Decimal("0.18")
CLEARANCE_MAX = Decimal("0.05")

# run_in_result constants.
TEMP_MAX = Decimal("95.0")
VIB_MAX = Decimal("4.5")
PARTICLE_MAX = 3200
RUN_IN_REQUIRED_MINUTES = 120

# warranty_eligibility constants.
WARRANTY_HOURS_LIMIT = 2000       # boundary: covered AT exactly 2000 (<=)
WARRANTY_CALENDAR_DAYS = 365


def _round_half_up(d):
    return int(Decimal(d).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def component_line_total_cents(action, labor_hours, material_cents, rush):
    """labor billed at the action-tier rate (rush-adjusted) + material.

    round_half_up per line: labor rounded first, then line total rounded
    (material is integer cents so the second rounding is normally a no-op).
    """
    rate = LABOR_RATE_CENTS[action]
    mult = RUSH_MULTIPLIER if rush else Decimal("1.0")
    labor = Decimal(str(labor_hours)) * Decimal(rate) * mult
    labor_cents = _round_half_up(labor)
    return _round_half_up(Decimal(labor_cents) + Decimal(material_cents))


def freight_charge_cents(weight_kg, rigging_bay_hours):
    """Tiered freight by weight class + rigging hours at RIGGING_HOURLY_CENTS.

    Overweight tier: ceil for each started 500-kg block beyond 2000 kg.
    """
    if weight_kg <= 500:
        base = 45000
    elif weight_kg <= 2000:
        base = 120000
    else:
        blocks = -(-(weight_kg - 2000) // 500)  # ceil division
        base = 120000 + blocks * 18000
    return base + rigging_bay_hours * RIGGING_HOURLY_CENTS


def assembly_within_tolerance(backlash_mm, radial_clearance_mm, axial_clearance_mm):
    b = Decimal(str(backlash_mm))
    r = Decimal(str(radial_clearance_mm))
    a = Decimal(str(axial_clearance_mm))
    return (BACKLASH_MIN <= b <= BACKLASH_MAX
            and r <= CLEARANCE_MAX
            and a <= CLEARANCE_MAX)


def run_in_result(duration_minutes, max_temp_c, vibration_mm_s, oil_particle_count):
    if duration_minutes != RUN_IN_REQUIRED_MINUTES:
        return "FAIL"
    if Decimal(str(max_temp_c)) > TEMP_MAX:
        return "FAIL"
    if Decimal(str(vibration_mm_s)) > VIB_MAX:
        return "FAIL"
    if oil_particle_count > PARTICLE_MAX:
        return "FAIL"
    return "PASS"
