"""Materials cost and draw calculation (PRD §3.5 / §3.6).

provisional (at placement) vs final (at dispense). Self-pay orders draw nothing.
"""
from decimal import Decimal, ROUND_HALF_UP

BASE_FRAME_ALLOWANCE_CENTS = 13000
FRAME_TIER_MULT = {
    "STANDARD": "1.00",
    "PREMIUM": "1.20",
    "DESIGNER": "1.50",
}


def frame_cap(frame_brand_tier):
    """round_half_up(BASE_FRAME_ALLOWANCE_CENTS * tier_mult) to whole cents."""
    product = Decimal(BASE_FRAME_ALLOWANCE_CENTS) * Decimal(FRAME_TIER_MULT[frame_brand_tier])
    return int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_draw(frame_charge, lens_charge, frame_brand_tier, available_room):
    """Return (draw, patient_materials_cost) given the room available.

    retail = frame + lens
    covered_frame = min(frame_charge, frame_cap(tier))
    desired_draw = covered_frame + lens_charge
    draw = min(desired_draw, available_room)
    patient_materials = retail - draw
    """
    retail = frame_charge + lens_charge
    cap = frame_cap(frame_brand_tier)
    covered_frame = min(frame_charge, cap)
    desired_draw = covered_frame + lens_charge
    draw = min(desired_draw, available_room)
    if draw < 0:
        draw = 0
    patient_materials = retail - draw
    return draw, patient_materials
