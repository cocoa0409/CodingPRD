"""Calculation rules (integer-cents money, Decimal round-half-up)."""
from decimal import Decimal, ROUND_HALF_UP

# -- thresholds --------------------------------------------------------------
BLL_CASE_THRESHOLD_UG_DL = Decimal("3.5")
BLL_CLASS_II_MIN = Decimal("20")
BLL_CLASS_I_MIN = Decimal("45")

# -- dust-wipe clearance limits ---------------------------------------------
DUST_FLOOR_LIMIT = Decimal("10")
DUST_SILL_LIMIT = Decimal("100")
DUST_TROUGH_LIMIT = Decimal("400")

# -- grant subsidy -----------------------------------------------------------
BASE_UNIT_SUBSIDY_CENTS = 250000
SUBSIDY_CAP_CENTS = 1500000
INCOME_MULTIPLIER = {
    "EXTREMELY_LOW": Decimal("1.5"),
    "VERY_LOW": Decimal("1.25"),
    "LOW": Decimal("1.0"),
    "MODERATE": Decimal("0.75"),
}

# -- relocation reimbursement ------------------------------------------------
PER_DIEM_LODGING_CENTS = 12000
MEAL_RATE_CENTS_PER_OCCUPANT = 3500
ADMIN_FACTOR = Decimal("1.075")

# -- order compliance --------------------------------------------------------
ORDER_COMPLIANCE_DEADLINE_DAYS = 30
RELOCATION_CLEANING_BUFFER_DAYS = 3


def _round_half_up(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _to_decimal(n):
    return Decimal(str(n))


def result_class(bll):
    """Classify a blood-lead level against the reference thresholds."""
    v = _to_decimal(bll)
    if v >= BLL_CLASS_I_MIN:
        return "CLASS_I"
    if v >= BLL_CLASS_II_MIN:
        return "CLASS_II"
    if v >= BLL_CASE_THRESHOLD_UG_DL:
        return "CLASS_III"
    return "BELOW_THRESHOLD"


def priority_class(reference_bll):
    """Response-priority band for a case (CLASS_III is the floor)."""
    v = _to_decimal(reference_bll)
    if v >= BLL_CLASS_I_MIN:
        return "CLASS_I"
    if v >= BLL_CLASS_II_MIN:
        return "CLASS_II"
    return "CLASS_III"


def grant_subsidy(hazard_count, income_tier):
    mult = INCOME_MULTIPLIER[income_tier]
    raw = Decimal(BASE_UNIT_SUBSIDY_CENTS) * Decimal(hazard_count) * mult
    rounded = _round_half_up(raw)
    return min(SUBSIDY_CAP_CENTS, rounded)


def relocation_reimbursement(occupant_count, nights):
    raw_per_day = (Decimal(PER_DIEM_LODGING_CENTS)
                   + Decimal(MEAL_RATE_CENTS_PER_OCCUPANT) * Decimal(occupant_count)) * ADMIN_FACTOR
    per_day_cents = _round_half_up(raw_per_day)  # round PER DAY first
    return per_day_cents * nights  # then multiply by nights


def clearance_pass(floor_v, sill_v, trough_v):
    return (_to_decimal(floor_v) <= DUST_FLOOR_LIMIT
            and _to_decimal(sill_v) <= DUST_SILL_LIMIT
            and _to_decimal(trough_v) <= DUST_TROUGH_LIMIT)
