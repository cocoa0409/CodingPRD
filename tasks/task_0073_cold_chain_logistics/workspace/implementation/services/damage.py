"""Damage amount calculation (dual variant)."""

from decimal import Decimal

from services.precision import round_half_up_int


DAMAGE_FACTOR = {
    "MINOR": Decimal("0.30"),
    "MODERATE": Decimal("0.60"),
    "TOTAL_LOSS": Decimal("1.00"),
}


def compute_damage_amount_cents(assessment: dict, task: dict, vehicle: dict) -> int:
    """Compute damage_amount_cents per the pinned rule:
       1. per-unit value (variant-dependent)
       2. per-unit damage rounded half up to whole cents = floor/round(per_unit * factor * (1 - salvage_pct))
          (round half up)
       3. raw_total = per_unit_damage * damaged_quantity
       4. capped at Vehicle.insured_cap_cents
    """
    variant = assessment["variant"]
    if variant == "INSURED_VALUE":
        unit_value_cents = task["cargo_value_cents"] // task["cargo_quantity"]
    else:  # INVOICE_VALUE
        unit_value_cents = int(assessment["invoice_unit_value_cents"])

    factor = DAMAGE_FACTOR[assessment["damage_class"]]
    salvage = Decimal(str(assessment["salvage_pct"]))
    per_unit_raw = Decimal(unit_value_cents) * factor * (Decimal("1") - salvage)
    per_unit_damage_cents = round_half_up_int(per_unit_raw)
    raw_total = per_unit_damage_cents * int(assessment["damaged_quantity"])
    cap = int(vehicle["insured_cap_cents"])
    return min(raw_total, cap)
