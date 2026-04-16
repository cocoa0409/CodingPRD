"""Monetary calculations: adoption fee and boarding quote."""

from decimal import Decimal, ROUND_HALF_UP

SENIOR_AGE_MONTHS = 96
SENIOR_DISCOUNT = Decimal("0.5")
PEAK_UTILIZATION = Decimal("0.8")
PEAK_SURCHARGE = Decimal("0.1")
MEDICAL_MULTIPLIER = Decimal("1.5")
BEHAVIORAL_MULTIPLIER = Decimal("1.25")


def _round_half_up_to_int(d: Decimal) -> int:
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_adoption_fee(animal: dict, shelter: dict) -> int:
    if animal.get("adoption_fee_override") is not None:
        base = Decimal(str(animal["adoption_fee_override"]))
    else:
        base = Decimal(str(shelter["adoption_fee_base"]))
    if animal.get("age_months", 0) >= SENIOR_AGE_MONTHS:
        base = base * SENIOR_DISCOUNT
    return _round_half_up_to_int(base)


def compute_boarding_quote(shelter: dict, animal: dict, nights: int, reserved_slots_including_new: int) -> int:
    """Compute quoted_total. reserved_slots_including_new should be the reserved_slots AFTER
    the new reservation has been added (per PRD: 'at time of reservation')."""
    rate = Decimal(str(shelter["boarding_rate_per_night"]))
    base = rate * Decimal(nights)
    level = animal.get("special_care_level", "NONE")
    if level == "MEDICAL":
        mult = MEDICAL_MULTIPLIER
    elif level == "BEHAVIORAL":
        mult = BEHAVIORAL_MULTIPLIER
    else:
        mult = Decimal("1.0")
    capacity = Decimal(str(shelter["boarding_capacity"]))
    if capacity > 0:
        utilization = Decimal(reserved_slots_including_new) / capacity
    else:
        utilization = Decimal("0")
    if utilization >= PEAK_UTILIZATION:
        surcharge = base * PEAK_SURCHARGE
    else:
        surcharge = Decimal("0")
    total = (base * mult) + surcharge
    return _round_half_up_to_int(total)


def compute_final_total(shelter: dict, animal: dict, nights: int, had_peak_surcharge: bool, original_base: Decimal = None) -> int:
    """For check-out: recompute final_total based on actual nights. Peak surcharge from quote
    is NOT re-evaluated; only nights change. We reapply the same surcharge RATE if one applied."""
    rate = Decimal(str(shelter["boarding_rate_per_night"]))
    base = rate * Decimal(nights)
    level = animal.get("special_care_level", "NONE")
    if level == "MEDICAL":
        mult = MEDICAL_MULTIPLIER
    elif level == "BEHAVIORAL":
        mult = BEHAVIORAL_MULTIPLIER
    else:
        mult = Decimal("1.0")
    if had_peak_surcharge:
        surcharge = base * PEAK_SURCHARGE
    else:
        surcharge = Decimal("0")
    total = (base * mult) + surcharge
    return _round_half_up_to_int(total)
