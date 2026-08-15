"""Calculation rules (scaffold section 1.3 / PRD sections 2.5, 2.7, 3.2, 3.4-3.8).

All money is integer cents; every intermediate multiplication is rounded
half-up to whole cents before the next step. Percentages are rounded half-up
to one decimal place. Delay accrual is whole minutes truncated toward zero.
"""
from decimal import Decimal, ROUND_HALF_UP

# --- Constants -------------------------------------------------------------
DIM_DIVISOR = 194
FUEL_SURCHARGE_PCT = Decimal("0.22")
MIN_UTILIZATION_PCT = Decimal("60.0")
MIN_CONNECT_MINUTES = 45
ON_TIME_TARGET_PCT = Decimal("95.0")

SERVICE_DAYS = {"STANDARD": 3, "EXPEDITED": 2, "GUARANTEED": 1}
SERVICE_STANDARDS = ("STANDARD", "EXPEDITED", "GUARANTEED")

CLASS_RATE_CENTS = {
    "CLASS_50": 1800,
    "CLASS_55": 2000,
    "CLASS_60": 2150,
    "CLASS_65": 2350,
    "CLASS_70": 2500,
    "CLASS_85": 2900,
    "CLASS_100": 3400,
    "CLASS_125": 4100,
}
NMFC_CLASSES = tuple(CLASS_RATE_CENTS.keys())

ACCESSORIAL_RATE_CENTS = {
    "LIFTGATE": 7500,
    "NOTIFY": 3500,
    "RESIDENTIAL": 9000,
    "INSIDE": 12000,
}
ACCESSORIAL_CODES = tuple(ACCESSORIAL_RATE_CENTS.keys())

LIABILITY_PER_LB_CENTS = {
    "CLASS_50": 150,
    "CLASS_55": 200,
    "CLASS_60": 250,
    "CLASS_65": 300,
    "CLASS_70": 350,
    "CLASS_85": 450,
    "CLASS_100": 600,
    "CLASS_125": 800,
}
FREIGHT_MULTIPLE_CAP = 10

CASE_KINDS = ("OVERAGE", "SHORTAGE", "DAMAGE")
DOOR_KINDS = ("INBOUND", "OUTBOUND")


def _round_half_up_whole(d):
    return int(Decimal(d).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_1dp(d):
    return Decimal(d).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def dim_weight_lbs(length_in, width_in, height_in):
    """ceil(L*W*H / DIM_DIVISOR) in whole pounds."""
    return (length_in * width_in * height_in + DIM_DIVISOR - 1) // DIM_DIVISOR


def shipment_cube_cuft(length_in, width_in, height_in):
    """ceil(L*W*H / 1728) in whole cubic feet."""
    return (length_in * width_in * height_in + 1728 - 1) // 1728


def freight_rating(nmfc_class, chargeable_weight_lbs, accessorial_codes):
    """Pinned rounding order: line-haul rounded first, fuel computed on the
    rounded line-haul and itself rounded, whole-cent accessorials added last.

    GROSS variant: caller passes chargeable_weight_lbs == actual_weight_lbs.
    DIM variant: caller passes max(measured_weight_lbs, ceil(measured dims/194)).
    """
    rate = CLASS_RATE_CENTS[nmfc_class]
    linehaul_cents = _round_half_up_whole(
        Decimal(chargeable_weight_lbs) / Decimal(100) * Decimal(rate)
    )
    fuel_cents = _round_half_up_whole(Decimal(linehaul_cents) * FUEL_SURCHARGE_PCT)
    accessorial_cents = sum(ACCESSORIAL_RATE_CENTS[c] for c in accessorial_codes)
    return linehaul_cents + fuel_cents + accessorial_cents


def osd_liability(claimed_amount_cents, item_amounts_cents, actual_weight_lbs,
                  nmfc_class, rated_amount_cents):
    """Waterfall: award is the minimum of four ceilings, each rounded half-up
    to whole cents before the min()."""
    gross_claim_cents = sum(int(x) for x in item_amounts_cents)
    class_cap_cents = _round_half_up_whole(
        Decimal(actual_weight_lbs) * Decimal(LIABILITY_PER_LB_CENTS[nmfc_class])
    )
    freight_cap_cents = _round_half_up_whole(
        Decimal(rated_amount_cents) * Decimal(FREIGHT_MULTIPLE_CAP)
    )
    return min(claimed_amount_cents, gross_claim_cents, class_cap_cents,
               freight_cap_cents)


def utilization_pct(loaded_weight_lbs, max_weight_lbs, loaded_cube_cuft, max_cube_cuft):
    """max(weight ratio, cube ratio) * 100, rounded half-up to 1 decimal.
    Returns a Decimal."""
    ratio_w = Decimal(loaded_weight_lbs) / Decimal(max_weight_lbs)
    ratio_c = Decimal(loaded_cube_cuft) / Decimal(max_cube_cuft)
    return round_half_up_1dp(max(ratio_w, ratio_c) * Decimal(100))


def on_time_pct(shipments_on_time, shipments_due):
    """On-time percentage, 1 decimal half-up; 0.0 when nothing is due."""
    if shipments_due == 0:
        return Decimal("0.0")
    return round_half_up_1dp(
        Decimal(shipments_on_time) / Decimal(shipments_due) * Decimal(100)
    )
